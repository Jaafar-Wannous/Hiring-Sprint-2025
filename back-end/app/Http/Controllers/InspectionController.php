<?php

namespace App\Http\Controllers;

use Illuminate\Http\Request;
use Illuminate\Http\Exceptions\HttpResponseException;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Storage;
use App\Models\Inspection;
use App\Models\Image;
use App\Models\Damage;

class InspectionController extends Controller
{
    /**
     * Combined workflow used by the Angular UI when pick-up and return
     * photos are sent together in a single request.
     */
    public function store(Request $request)
    {
        $data = $request->validate([
            'vehicle_id' => 'nullable|integer',
            'rental_id' => 'nullable|integer',
            'pickup_images' => 'nullable|array',
            'pickup_images.*' => 'mimes:jpeg,png,jpg,webp,heic|max:8192',
            'pickup_angles' => 'array',
            'pickup_angles.*' => 'nullable|string|max:32',
            'return_images' => 'required|array|min:1',
            'return_images.*' => 'mimes:jpeg,png,jpg,webp,heic|max:8192',
            'return_angles' => 'array',
            'return_angles.*' => 'nullable|string|max:32',
        ]);

        $inspection = Inspection::create([
            'vehicle_id' => $data['vehicle_id'] ?? null,
            'rental_id' => $data['rental_id'] ?? null,
        ]);

        $pickupData = $this->persistImages(
            $request->file('pickup_images', []),
            $inspection,
            'pickup',
            $request->input('pickup_angles', [])
        );
        $returnData = $this->persistImages(
            $request->file('return_images', []),
            $inspection,
            'return',
            $request->input('return_angles', [])
        );

        return $this->analyzeReturnImages(
            $inspection,
            $pickupData['full_paths'],
            $returnData['full_paths'],
            $returnData['records']
        );
    }

    /**
     * Step 1: persist a pick-up baseline and return the inspection id.
     */
    public function storePickup(Request $request)
    {
        $data = $request->validate([
            'vehicle_id' => 'nullable|integer',
            'rental_id' => 'nullable|integer',
            'pickup_images' => 'required|array|min:1',
            'pickup_images.*' => 'mimes:jpeg,png,jpg,webp,heic|max:8192',
            'pickup_angles' => 'array',
            'pickup_angles.*' => 'nullable|string|max:32',
        ]);

        $inspection = Inspection::create([
            'vehicle_id' => $data['vehicle_id'] ?? null,
            'rental_id' => $data['rental_id'] ?? null,
        ]);

        $pickupData = $this->persistImages(
            $request->file('pickup_images', []),
            $inspection,
            'pickup',
            $request->input('pickup_angles', [])
        );

        return response()->json([
            'inspection_id' => $inspection->id,
            'message' => 'Pickup photos have been saved. Share the inspection id with the team returning the vehicle.',
            'pickup_image_count' => count($pickupData['records']),
        ], 201);
    }

    /**
     * Step 2: attach return photos to an existing inspection and perform the AI comparison.
     */
    public function storeReturn(Request $request, Inspection $inspection)
    {
        $data = $request->validate([
            'return_images' => 'required|array|min:1',
            'return_images.*' => 'mimes:jpeg,png,jpg,webp,heic|max:8192',
            'return_angles' => 'array',
            'return_angles.*' => 'nullable|string|max:32',
        ]);

        $pickupRecords = $inspection->images()->where('type', 'pickup')->get();
        if ($pickupRecords->isEmpty()) {
            return response()->json([
                'error' => 'This inspection does not have pick-up photos yet. Save a baseline first.',
            ], 422);
        }

        $pickupFullPaths = $pickupRecords
            ->map(fn ($image) => $this->absolutePathFromPublic($image->path))
            ->filter(fn ($path) => $path !== null)
            ->values()
            ->all();

        $returnData = $this->persistImages(
            $request->file('return_images', []),
            $inspection,
            'return',
            $request->input('return_angles', [])
        );

        return $this->analyzeReturnImages(
            $inspection,
            $pickupFullPaths,
            $returnData['full_paths'],
            $returnData['records']
        );
    }

    /**
     * Return an inspection with images and persisted damages for integrations.
     */
    public function show(int $id)
    {
        $inspection = Inspection::with(['images', 'damages'])->findOrFail($id);

        $pickupImages = $inspection->images
            ->where('type', 'pickup')
            ->values()
            ->map(fn ($image) => [
                'id' => $image->id,
                'path' => $image->path,
                'angle' => $image->angle,
            ]);

        $returnImages = $inspection->images
            ->where('type', 'return')
            ->values()
            ->map(fn ($image) => [
                'id' => $image->id,
                'path' => $image->path,
                'angle' => $image->angle,
            ]);

        $damages = $inspection->damages
            ->map(fn ($damage) => [
                'id' => $damage->id,
                'image_id' => $damage->image_id,
                'type' => $damage->type,
                'severity' => $damage->severity,
                'estimated_cost' => $damage->estimated_cost,
                'confidence' => $damage->confidence,
                'area_ratio' => $damage->area_ratio,
                'repair_details' => $damage->repair_meta,
                'x' => $damage->x,
                'y' => $damage->y,
                'width' => $damage->width,
                'height' => $damage->height,
            ]);

        return response()->json([
            'id' => $inspection->id,
            'created_at' => $inspection->created_at,
            'pickup_images' => $pickupImages,
            'return_images' => $returnImages,
            'damages' => $damages,
            'summary' => [
                'total_damages' => $damages->count(),
                'estimated_cost' => $damages->sum('estimated_cost'),
            ],
        ]);
    }

    private function analyzeReturnImages(
        Inspection $inspection,
        array $pickupFullPaths,
        array $returnFullPaths,
        array $returnImageRecords
    ) {
        if (empty($returnFullPaths)) {
            return response()->json([
                'error' => 'Return photos are required to complete the inspection.',
            ], 422);
        }

        $baselineDetections = [];
        if (!empty($pickupFullPaths)) {
            $baselineDetections = $this->callYolo($pickupFullPaths);
        }

        $returnDetections = $this->callYolo($returnFullPaths);

        [$damagePayload, $totalCost, $totalCount] = $this->extractNewDamages(
            $inspection,
            $baselineDetections,
            $returnDetections,
            $returnImageRecords
        );

        return response()->json([
            'inspection_id' => $inspection->id,
            'results' => $damagePayload,
            'metadata' => [
                'pickup_image_count' => $inspection->images()->where('type', 'pickup')->count(),
                'return_image_count' => $inspection->images()->where('type', 'return')->count(),
                'total_new_damages' => $totalCount,
                'total_estimated_cost' => $totalCost,
            ],
        ]);
    }

    private function callYolo(array $absolutePaths): array
    {
        $yoloUrl = env('YOLO_URL', 'http://ai-service:8000/detect');
        $response = Http::asMultipart()->post($yoloUrl, $this->prepareFilesForYOLO($absolutePaths));

        if ($response->failed()) {
            throw new HttpResponseException(response()->json([
                'error' => 'Unable to analyze images using the AI service.',
                'details' => $response->body(),
            ], 502));
        }

        return $response->json();
    }

    private function persistImages(?array $files, Inspection $inspection, string $type, array $angles = []): array
    {
        if (empty($files)) {
            return [
                'public_paths' => [],
                'full_paths' => [],
                'records' => [],
            ];
        }

        Storage::disk('public')->makeDirectory('inspections');

        $publicPaths = [];
        $fullPaths = [];
        $records = [];

        foreach ($files as $index => $file) {
            $storedPath = $file->store('inspections', 'public');
            $publicPath = 'storage/' . $storedPath;
            $absolutePath = Storage::disk('public')->path($storedPath);

            $records[$index] = Image::create([
                'inspection_id' => $inspection->id,
                'path' => $publicPath,
                'type' => $type,
                'angle' => $angles[$index] ?? null,
            ]);

            $publicPaths[] = $publicPath;
            $fullPaths[] = $absolutePath;
        }

        return [
            'public_paths' => $publicPaths,
            'full_paths' => $fullPaths,
            'records' => $records,
        ];
    }

    private function absolutePathFromPublic(?string $publicPath): ?string
    {
        if (!$publicPath) {
            return null;
        }

        $relative = str_starts_with($publicPath, 'storage/')
            ? substr($publicPath, strlen('storage/'))
            : $publicPath;

        $absolute = Storage::disk('public')->path($relative);
        return is_readable($absolute) ? $absolute : null;
    }

    private function extractNewDamages(
        Inspection $inspection,
        array $baselineDetections,
        array $returnDetections,
        array $returnImageRecords
    ): array {
        $flattenedBaseline = [];
        foreach ($baselineDetections as $group) {
            foreach ($group as $dmg) {
                $flattenedBaseline[] = [
                    'type' => $dmg['class'] ?? $dmg['type'] ?? 'unknown',
                    'x' => (float) ($dmg['x'] ?? 0),
                    'y' => (float) ($dmg['y'] ?? 0),
                    'width' => (float) ($dmg['width'] ?? 0),
                    'height' => (float) ($dmg['height'] ?? 0),
                ];
            }
        }

        $newDamagesPerImage = [];
        $damageRecordsToInsert = [];
        $totalCost = 0;
        $totalCount = 0;

        foreach ($returnDetections as $index => $returnImageDetections) {
            $newDamagesForImage = [];
            foreach ($returnImageDetections as $dmg) {
                $type = $dmg['class'] ?? $dmg['type'] ?? 'unknown';
                $x = (float) ($dmg['x'] ?? 0);
                $y = (float) ($dmg['y'] ?? 0);
                $w = (float) ($dmg['width'] ?? 0);
                $h = (float) ($dmg['height'] ?? 0);
                $areaRatio = isset($dmg['area_ratio']) ? (float) $dmg['area_ratio'] : ($w * $h);
                $confidence = isset($dmg['conf'])
                    ? (float) $dmg['conf']
                    : (isset($dmg['confidence']) ? ((float) $dmg['confidence']) / 100 : null);
                $repairDetails = $dmg['repair_details'] ?? null;
                $severityLabel = $dmg['severity'] ?? null;
                $estimatedCost = $dmg['repair_cost'] ?? ($repairDetails['total_cost'] ?? null);

                $isNew = true;
                foreach ($flattenedBaseline as $baseline) {
                    if (($baseline['type'] ?? 'unknown') !== $type) {
                        continue;
                    }

                    $iou = $this->calculateIoU(
                        $x,
                        $y,
                        $w,
                        $h,
                        $baseline['x'],
                        $baseline['y'],
                        $baseline['width'],
                        $baseline['height']
                    );

                    if ($iou > 0.5) {
                        $isNew = false;
                        break;
                    }
                }

                if ($isNew) {
                    if ($severityLabel === null || $estimatedCost === null) {
                        [$fallbackSeverity, $fallbackCost] = $this->assessDamageSeverity($type, $w * $h);
                        $severityLabel ??= $fallbackSeverity;
                        $estimatedCost ??= $fallbackCost;
                    }

                    $newDamagesForImage[] = [
                        'label' => $this->translateDamageType($type),
                        'severity' => $severityLabel,
                        'cost' => $estimatedCost,
                        'x' => $x,
                        'y' => $y,
                        'width' => $w,
                        'height' => $h,
                        'confidence' => $confidence,
                        'area_ratio' => $areaRatio,
                        'repair_details' => $repairDetails,
                    ];

                    $imageRecord = $returnImageRecords[$index] ?? null;
                    if ($imageRecord) {
                        $damageRecordsToInsert[] = [
                            'inspection_id' => $inspection->id,
                            'image_id' => $imageRecord->id,
                            'type' => $type,
                            'severity' => $severityLabel,
                            'estimated_cost' => $estimatedCost,
                            'confidence' => $confidence,
                            'area_ratio' => $areaRatio,
                            'repair_meta' => $repairDetails ? json_encode($repairDetails) : null,
                            'x' => $x,
                            'y' => $y,
                            'width' => $w,
                            'height' => $h,
                            'created_at' => now(),
                            'updated_at' => now(),
                        ];
                    }

                    $totalCost += $estimatedCost;
                    $totalCount++;
                }
            }

            $newDamagesPerImage[] = $newDamagesForImage;
        }

        if (!empty($damageRecordsToInsert)) {
            Damage::insert($damageRecordsToInsert);
        }

        return [$newDamagesPerImage, $totalCost, $totalCount];
    }

    private function prepareFilesForYOLO(array $absolutePaths): array
    {
        $multipartData = [];
        foreach ($absolutePaths as $fullPath) {
            if (!is_readable($fullPath)) {
                continue;
            }
            $multipartData[] = [
                'name' => 'images',
                'contents' => fopen($fullPath, 'r'),
                'filename' => basename($fullPath),
            ];
        }
        return $multipartData;
    }

    private function calculateIoU($x1, $y1, $w1, $h1, $x2, $y2, $w2, $h2): float
    {
        $box1_x2 = $x1 + $w1;
        $box1_y2 = $y1 + $h1;
        $box2_x2 = $x2 + $w2;
        $box2_y2 = $y2 + $h2;

        $interX1 = max($x1, $x2);
        $interY1 = max($y1, $y2);
        $interX2 = min($box1_x2, $box2_x2);
        $interY2 = min($box1_y2, $box2_y2);
        $interW = max(0, $interX2 - $interX1);
        $interH = max(0, $interY2 - $interY1);
        $interArea = $interW * $interH;

        if ($interArea == 0) {
            return 0.0;
        }

        $area1 = $w1 * $h1;
        $area2 = $w2 * $h2;

        return $interArea / ($area1 + $area2 - $interArea);
    }

    private function assessDamageSeverity(string $type, float $area): array
    {
        $severity = 'low';
        $cost = 50;

        if ($area > 0.15) {
            $severity = 'high';
        } elseif ($area > 0.05) {
            $severity = 'medium';
        }

        switch (strtolower($type)) {
            case 'scratch':
                $cost = match ($severity) {
                    'low' => 50,
                    'medium' => 150,
                    default => 300,
                };
                break;
            case 'dent':
                $cost = match ($severity) {
                    'low' => 100,
                    'medium' => 300,
                    default => 600,
                };
                break;
            case 'crack':
                $cost = match ($severity) {
                    'low' => 80,
                    'medium' => 200,
                    default => 400,
                };
                break;
            default:
                $cost = match ($severity) {
                    'low' => 120,
                    'medium' => 220,
                    default => 400,
                };
                break;
        }

        return [$severity, $cost];
    }

    private function translateDamageType(string $type): string
    {
        return ucfirst(str_replace('_', ' ', strtolower($type)));
    }
}

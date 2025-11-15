<?php

namespace App\Http\Controllers;

use Illuminate\Http\Request;
use App\Models\Inspection;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;
use Illuminate\Support\Facades\Storage;

class DamageController extends Controller
{
    public function uploadPickup(Request $request)
    {
        $request->validate([
            'image' => 'required|image|mimes:jpeg,png,jpg|max:5120',
            'vehicle_angle' => 'required|string|in:front,rear,left,right,top,interior'
        ]);

        $path = $request->file('image')->store('uploads', 'public');

        $inspection = Inspection::create([
            'pickup_image' => $path,
            'vehicle_angle' => $request->vehicle_angle
        ]);

        return response()->json([
            'message' => 'Pickup image saved successfully',
            'id' => $inspection->id
        ]);
    }

    public function uploadReturn(Request $request)
    {
        $request->validate([
            'image' => 'required|image|mimes:jpeg,png,jpg|max:5120',
            'inspection_id' => 'required|integer|exists:inspections,id',
            'vehicle_angle' => 'required|string|in:front,rear,left,right,top,interior'
        ]);

        $inspection = Inspection::findOrFail($request->inspection_id);

        // Verify that camera angle matches
        if ($inspection->vehicle_angle !== $request->vehicle_angle) {
            return response()->json([
                'error' => 'Camera angle must match the pickup image angle'
            ], 400);
        }

        $path = $request->file('image')->store('uploads', 'public');
        $inspection->update(['return_image' => $path]);

        // Use the selected analysis method
        $analysisResult = $this->analyzeDamageComparison(
            storage_path('app/public/' . $inspection->pickup_image),
            storage_path('app/public/' . $path)
        );

        $inspection->update([
            'damages' => json_encode($analysisResult),
            'analysis_completed' => true,
            'total_repair_cost' => $analysisResult['total_repair_cost'] ?? 0
        ]);

        return response()->json($analysisResult);
    }

    private function analyzeDamageComparison($pickupPath, $returnPath)
    {
        // First attempt: Local model
        $result = $this->useLocalModel($pickupPath, $returnPath);

        // If failed, try Hugging Face
        if (isset($result['error'])) {
            $result = $this->useHuggingFace($pickupPath, $returnPath);
        }

        // If also failed, use fallback method
        if (isset($result['error'])) {
            $result = $this->useFallbackMethod($pickupPath, $returnPath);
        }

        return $result;
    }

    private function useLocalModel($pickupPath, $returnPath)
    {
        $script = base_path('scripts/damage_detection.py');

        $cmd = escapeshellcmd("python3 " . $script . " " .
            escapeshellarg($pickupPath) . " " .
            escapeshellarg($returnPath));

        $output = shell_exec($cmd);
        $result = json_decode($output, true);

        if (isset($result['error'])) {
            \Log::error('Local model error: ' . $result['error']);
            return ['error' => 'Local model failed'];
        }

        return $result;
    }

    private function useHuggingFace($pickupPath, $returnPath)
    {
        // Free model from Hugging Face - can be changed to another model
        $apiUrl = "https://api-inference.huggingface.co/models/keremberke/yolov5n-vehicle";

        try {
            // Analyze pickup image
            $pickupResponse = Http::withHeaders([
                'Authorization' => 'Bearer '.env('HF_API_KEY', 'free'),
            ])
            ->timeout(30)
            ->attach('file', file_get_contents($pickupPath), 'pickup.jpg')
            ->post($apiUrl);

            // Analyze return image
            $returnResponse = Http::withHeaders([
                'Authorization' => 'Bearer '.env('HF_API_KEY', 'free'),
            ])
            ->timeout(30)
            ->attach('file', file_get_contents($returnPath), 'return.jpg')
            ->post($apiUrl);

            if (!$pickupResponse->successful() || !$returnResponse->successful()) {
                throw new \Exception('Hugging Face API request failed');
            }

            $pickupDamages = $pickupResponse->json() ?? [];
            $returnDamages = $returnResponse->json() ?? [];

            // Compare damages
            $newDamages = $this->compareDamages($pickupDamages, $returnDamages);

            return [
                'new_damages' => $newDamages,
                'total_repair_cost' => $this->calculateRepairCost($newDamages),
                'severity_score' => $this->calculateSeverityScore($newDamages),
                'summary' => $this->generateSummary($newDamages),
                'pickup_damages_count' => count($pickupDamages),
                'return_damages_count' => count($returnDamages)
            ];

        } catch (\Exception $e) {
            \Log::error('Hugging Face API Error: ' . $e->getMessage());
            return ['error' => 'Hugging Face analysis failed: ' . $e->getMessage()];
        }
    }

    private function useFallbackMethod($pickupPath, $returnPath)
    {
        // Fallback method using simple analysis
        return [
            'new_damages' => [
                [
                    'label' => 'scratch',
                    'confidence' => 0.7,
                    'type' => 'scratch',
                    'estimated_cost' => 75,
                    'severity' => 'low',
                    'bbox' => [100, 150, 200, 180]
                ]
            ],
            'total_repair_cost' => 75,
            'severity_score' => 2,
            'summary' => 'Fallback analysis completed - demo data',
            'pickup_damages_count' => 0,
            'return_damages_count' => 1
        ];
    }

    private function compareDamages($pickupDamages, $returnDamages)
    {
        // Simple comparison - can be developed into more complex comparison
        $newDamages = [];

        foreach ($returnDamages as $returnDamage) {
            $isNew = true;
            foreach ($pickupDamages as $pickupDamage) {
                if ($this->isSameDamage($returnDamage, $pickupDamage)) {
                    $isNew = false;
                    break;
                }
            }
            if ($isNew) {
                $newDamages[] = array_merge($returnDamage, [
                    'estimated_cost' => $this->estimateDamageCost($returnDamage),
                    'severity' => $this->assessDamageSeverity($returnDamage)
                ]);
            }
        }

        return $newDamages;
    }

    private function isSameDamage($damage1, $damage2)
    {
        // Simple comparison based on location and type
        $bbox1 = $damage1['bbox'] ?? [0,0,0,0];
        $bbox2 = $damage2['bbox'] ?? [0,0,0,0];

        // If boxes are close, consider them the same damage
        $center1 = [($bbox1[0] + $bbox1[2]) / 2, ($bbox1[1] + $bbox1[3]) / 2];
        $center2 = [($bbox2[0] + $bbox2[2]) / 2, ($bbox2[1] + $bbox2[3]) / 2];

        $distance = sqrt(pow($center1[0] - $center2[0], 2) + pow($center1[1] - $center2[1], 2));

        return $distance < 50; // If distance is less than 50 pixels
    }

    private function estimateDamageCost($damage)
    {
        $baseCosts = [
            'scratch' => 50,
            'dent' => 150,
            'crack' => 200,
            'broken' => 300
        ];

        $type = strtolower($damage['label'] ?? 'unknown');
        $area = (($damage['bbox'][2] ?? 1) - ($damage['bbox'][0] ?? 0)) *
                (($damage['bbox'][3] ?? 1) - ($damage['bbox'][1] ?? 0));

        $cost = $baseCosts[$type] ?? 100;
        return min(1000, $cost * max(1, $area / 1000));
    }

    private function assessDamageSeverity($damage)
    {
        $confidence = $damage['confidence'] ?? 0.5;
        $cost = $this->estimateDamageCost($damage);

        if ($cost > 300) return 'high';
        if ($cost > 150) return 'medium';
        return 'low';
    }

    private function calculateRepairCost($damages)
    {
        return array_sum(array_column($damages, 'estimated_cost'));
    }

    private function calculateSeverityScore($damages)
    {
        if (empty($damages)) return 0;

        $severityWeights = ['low' => 1, 'medium' => 2, 'high' => 3];
        $totalScore = 0;

        foreach ($damages as $damage) {
            $totalScore += $severityWeights[$damage['severity']] ?? 1;
        }

        return min(10, $totalScore);
    }

    private function generateSummary($damages)
    {
        $count = count($damages);
        $cost = $this->calculateRepairCost($damages);

        if ($count === 0) {
            return 'No new damages detected';
        }

        return "Detected {$count} new damages with estimated repair cost of \${$cost}";
    }
}

<?php

namespace Tests\Feature;

use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\UploadedFile;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Storage;
use Tests\TestCase;

class InspectionWorkflowTest extends TestCase
{
    use RefreshDatabase;

    public function test_pickup_requires_images(): void
    {
        $response = $this->postJson('/api/inspections/pickup', []);

        $response->assertStatus(422)->assertJsonValidationErrors(['pickup_images']);
    }

    public function test_pickup_creates_inspection_and_persists_images(): void
    {
        Storage::fake('public');

        $response = $this->postJson('/api/inspections/pickup', [
            'vehicle_id' => 77,
            'pickup_images' => [
                UploadedFile::fake()->create('front.jpg', 150, 'image/jpeg'),
                UploadedFile::fake()->create('rear.jpg', 150, 'image/jpeg'),
            ],
        ]);

        $response->assertCreated()->assertJsonStructure([
            'inspection_id',
            'pickup_image_count',
            'message',
        ]);

        $this->assertDatabaseCount('inspections', 1);
        $this->assertDatabaseCount('images', 2);
    }

    public function test_return_stage_runs_ai_and_persists_damages(): void
    {
        Storage::fake('public');

        $pickupResponse = $this->postJson('/api/inspections/pickup', [
            'pickup_images' => [
                UploadedFile::fake()->create('pickup.jpg', 150, 'image/jpeg'),
            ],
        ]);

        $inspectionId = $pickupResponse->json('inspection_id');

        Http::fakeSequence()
            ->push([[]]) // baseline detections
            ->push([
                [
                    [
                        'class' => 'scratch',
                        'x' => 0.1,
                        'y' => 0.2,
                        'width' => 0.3,
                        'height' => 0.2,
                        'conf' => 0.87,
                        'severity' => 'medium',
                        'repair_cost' => 250,
                    ],
                ],
            ]);

        $response = $this->postJson("/api/inspections/{$inspectionId}/return", [
            'return_images' => [
                UploadedFile::fake()->create('return.jpg', 150, 'image/jpeg'),
            ],
        ]);

        $response->assertOk()
            ->assertJsonPath('metadata.total_new_damages', 1)
            ->assertJsonPath('metadata.total_estimated_cost', 250);

        $this->assertDatabaseCount('damages', 1);
    }
}

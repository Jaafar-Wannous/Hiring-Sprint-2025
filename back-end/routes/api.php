<?php

use Illuminate\Support\Facades\Route;
use App\Http\Controllers\InspectionController;

Route::middleware('cors')->group(function () {
    Route::post('/inspections', [InspectionController::class, 'store']);
    Route::post('/inspections/pickup', [InspectionController::class, 'storePickup']);
    Route::post('/inspections/{inspection}/return', [InspectionController::class, 'storeReturn']);
    Route::get('/inspections/{id}', [InspectionController::class, 'show']);
});

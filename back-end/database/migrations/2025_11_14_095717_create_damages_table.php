<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    /**
     * Run the migrations.
     */
    public function up(): void
    {
        Schema::create('damages', function (Blueprint $table) {
            $table->id();
            $table->foreignId('inspection_id')->constrained('inspections')->onDelete('cascade');
            $table->foreignId('image_id')->constrained('images')->onDelete('cascade');
            $table->string('type');        // damage type (scratch, dent, crack, etc)
            $table->string('severity');   
            $table->decimal('estimated_cost', 8, 2)->nullable(); // estimated repair cost in USD (or required currency)
            // store damage bounding box coordinates as percentages of original image (0 to 1)
            $table->float('x', 5);      // horizontal start point percentage
            $table->float('y', 5);      // vertical start point percentage
            $table->float('width', 5);  // width percentage
            $table->float('height', 5); // height percentage
            $table->timestamps();
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('damages');
    }
};

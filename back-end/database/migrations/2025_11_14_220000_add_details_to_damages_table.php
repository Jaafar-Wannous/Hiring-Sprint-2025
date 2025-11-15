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
        Schema::table('damages', function (Blueprint $table) {
            $table->float('confidence', 5)->nullable()->after('estimated_cost');
            $table->float('area_ratio', 8, 5)->nullable()->after('confidence');
            $table->json('repair_meta')->nullable()->after('area_ratio');
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::table('damages', function (Blueprint $table) {
            $table->dropColumn(['confidence', 'area_ratio', 'repair_meta']);
        });
    }
};

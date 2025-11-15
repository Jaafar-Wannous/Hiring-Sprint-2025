<?php
// app/Models/Damage.php
namespace App\Models;
use Illuminate\Database\Eloquent\Model;

class Damage extends Model
{
    protected $fillable = [
        'inspection_id',
        'image_id',
        'type',
        'severity',
        'estimated_cost',
        'confidence',
        'area_ratio',
        'repair_meta',
        'x',
        'y',
        'width',
        'height',
    ];

    protected $casts = [
        'repair_meta' => 'array',
    ];

    public function inspection() {
        return $this->belongsTo(Inspection::class);
    }

    public function image() {
        return $this->belongsTo(Image::class);
    }
}

<?php
// app/Models/Image.php
namespace App\Models;
use Illuminate\Database\Eloquent\Model;

class Image extends Model
{
    protected $fillable = ['inspection_id', 'path', 'type', 'angle'];

    public function inspection() {
        return $this->belongsTo(Inspection::class);
    }

    public function damages() {
        return $this->hasMany(Damage::class);
    }
}

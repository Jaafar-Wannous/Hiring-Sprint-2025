<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class Inspection extends Model
{
    protected $guarded = [];

    public $timestamps = false;

    public function images()
    {
        return $this->hasMany(Image::class);
    }

    public function damages()
    {
        return $this->hasMany(Damage::class);
    }
}

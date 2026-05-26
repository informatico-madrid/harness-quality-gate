<?php
namespace App;

class Service {
    public function process(string $data): string {
        return strtoupper($data);
    }
}

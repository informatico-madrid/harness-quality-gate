<?php
use App\Service;

it('processes data to uppercase', function () {
    $svc = new Service();
    expect($svc->process('hello'))->toBe('HELLO');
});

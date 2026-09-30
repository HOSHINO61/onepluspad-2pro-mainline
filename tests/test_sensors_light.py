# SPDX-License-Identifier: GPL-2.0-only
"""Light startup evidence and a real nested Claim/Release reproducer."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
INPUTS = REPO / 'packaging/sensors'
GATE = REPO / 'packaging/erhai-sensors/tree/usr/libexec/erhai-sensors/ssc-sample-gate'


class LightGate(unittest.TestCase):
    def run_gate(self, body, bound=2):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'registry').mkdir()
            (root / 'registry/config').write_text('{}')
            cli = root / 'ssccli'
            cli.write_text('#!/bin/sh\nif [ "$1" = --sensor=accelerometer ]; then\n' +
                           "echo 'Accelerometer sensor measurement: X=0 Y=0 Z=9.81 m/s²'\n" * 3 +
                           'exit 0\nfi\n' + body)
            cli.chmod(0o755)
            env = dict(os.environ, LC_ALL='C', ERHAI_SENSORS_REGISTRY=str(root / 'registry'),
                       ERHAI_SENSORS_SSCCLI=str(cli), ERHAI_SENSORS_STATE=str(root / 'state'),
                       ERHAI_SENSORS_BOUND=str(bound))
            result = subprocess.run([str(GATE)], env=env, capture_output=True, text=True, timeout=12)
            return result, (root / 'state/light-gate.result').read_text()

    def test_single_on_change_sample_and_darkness(self):
        for level in ('0.000000', '125.250000', '200000.000000'):
            result, record = self.run_gate(f"echo 'Light sensor measurement: {level} Lux'\n")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('result=pass', record)

    def test_missing_or_invalid_data(self):
        for body in (':\n', "echo 'Light sensor measurement: nan Lux'\n",
                     "echo 'Light sensor measurement: -1.000000 Lux'\n",
                     "echo 'Light sensor measurement: 200001.000000 Lux'\n",
                     "echo 'Light sensor measurement: 10.000000 raw'\n",
                     "echo 'Light sensor measurement: 20.000000 Lux'\necho 'Light sensor measurement: inf Lux'\n"):
            result, record = self.run_gate(body)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('result=fail', record)

    def test_lifecycle_failure_after_data_is_not_pass(self):
        prefix = "echo 'Light sensor measurement: 10.000000 Lux'\n"
        for suffix in ('exit 2\n', "echo 'Unable to close light sensor: failed'\n", 'exec sleep 60\n'):
            result, record = self.run_gate(prefix + suffix, bound=1)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('result=fail', record)


PRELUDE = r'''
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef int gboolean;
typedef struct { const char *message; } GError;
typedef struct {
    void *sensor;
    unsigned long measurement_id;
    gboolean polling_requested, polling_changing;
} DrvData;
typedef struct { void *priv; } SensorDevice;
#define TRUE 1
#define FALSE 0
#define g_autoptr(type) type *
#define G_CALLBACK(fn) NULL
#define g_signal_connect(sensor, name, callback, data) 1UL
#define g_clear_signal_handler(id, sensor) (*(id) = 0)
#define g_warning(...) ((void)0)
static void ssc_light_set_polling(SensorDevice *, gboolean);
static SensorDevice *current;
static int busy, overlap, mode, hook, opens, closes;
static GError failure = { "injected" };
static int ssc_sensor_light_open_sync(void *s, void *c, GError **error) {
    (void)s; (void)c;
    opens++; busy++;
    if (!hook++) {
        ssc_light_set_polling(current, FALSE);
        if (mode == 2) ssc_light_set_polling(current, TRUE);
    }
    busy--;
    if (mode == 3) { *error = &failure; return FALSE; }
    return TRUE;
}
static int ssc_sensor_light_close_sync(void *s, void *c, GError **error) {
    (void)s; (void)c; (void)error;
    closes++;
    if (busy) overlap++;
    return TRUE;
}
'''
EPILOGUE = r'''
int main(int argc, char **argv) {
    (void)argc;
    DrvData data = { .sensor = &data };
    SensorDevice device = { .priv = &data };
    current = &device;
    mode = atoi(argv[1]);
    ssc_light_set_polling(&device, TRUE);
    if (overlap || data.polling_changing) return 3;
    if (mode == 1 && (opens != 1 || closes != 1 || data.measurement_id)) return 4;
    if (mode == 2 && (opens != 1 || closes || !data.measurement_id)) return 5;
    if (mode == 3 && (opens != 1 || closes || data.measurement_id)) return 6;
    return 0;
}
'''


class LightTransitions(unittest.TestCase):
    def test_nested_release_and_latest_claim(self):
        pin = next(s for s in json.loads((INPUTS / 'sources.json').read_text())['sources']
                   if s['name'] == 'iio-sensor-proxy')
        archive = REPO.parents[1] / 'cache/sensors' / pin['archive']
        if not archive.is_file() or not shutil.which('cc'):
            self.skipTest('requires pinned source cache and host C compiler')
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), pin['sha256'])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with tarfile.open(archive) as tar:
                text = tar.extractfile(pin['directory'] + '/src/drv-ssc-light.c').read().decode()
            (root / 'src').mkdir()
            source = root / 'src/drv-ssc-light.c'
            source.write_text(text)
            patch = next(p for p in pin['patches'] if 'ssc-light-polling' in p['file'])
            path = INPUTS / patch['file']
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), patch['sha256'])
            subprocess.run(['patch', '-p1', '--fuzz=0', '--batch', '-i', str(path)], cwd=root,
                           check=True, capture_output=True)
            for name, content in (('upstream', text), ('candidate', source.read_text())):
                start = content.index('static void\nssc_light_set_polling')
                end = content.index('\n}\n', start) + 3
                unit = root / f'{name}.c'
                unit.write_text(PRELUDE + content[start:end] + EPILOGUE)
                binary = root / name
                subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', str(unit), '-o', str(binary)],
                               check=True, capture_output=True)
                if name == 'upstream':
                    self.assertNotEqual(subprocess.run([str(binary), '1']).returncode, 0,
                                        'the unpatched driver must reproduce the nested close')
                else:
                    for scenario in ('1', '2', '3'):
                        self.assertEqual(subprocess.run([str(binary), scenario]).returncode, 0)


if __name__ == '__main__':
    unittest.main()

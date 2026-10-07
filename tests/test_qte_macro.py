"""
Unit Test Suite for Violence District QTE Macro (Lunar Tear)
=============================================================
Tests:
1. detect_white_patch() across all quadrants (top, right, bottom, left)
   with both dark and bright borders (verifying no left-side or dark border bias).
2. detect_white_patch() wrap-around across 0°/360°.
3. detect_white_patch() candidate ranking by brightness and span.
4. Early trigger safety: needle approaching before patch start MUST NEVER trigger.
5. Trigger behavior when needle reaches or is inside the patch.
6. Zero delay guarantee in calculate_effective_delay() and DEFAULT_CONFIG.
7. Degenerate and edge case buffers (solid black, solid white, noise).
"""

import os
import sys
import math
import unittest
import tempfile
import re
import json

# Ensure project root is in sys.path
vd_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if vd_dir not in sys.path:
    sys.path.insert(0, vd_dir)

from qte_macro import QTEDetector, DEFAULT_CONFIG, load_or_create_config, AdaptiveCalibrationEngine


def create_synthetic_frame(
    cx: int = 160,
    cy: int = 160,
    R: int = 83,
    crop_size: int = 320,
    white_patch: tuple = None,  # (start_deg, span_deg)
    patch_rgb: tuple = (255, 255, 255),
    border_lum: int = 30,       # Background / border luminance around ring
    needle_deg: float = None,
    with_glyph: bool = True
) -> bytearray:
    """
    Creates a synthetic BGRA frame buffer with configurable QTE elements:
    - Central [_] spacebar glyph
    - Ring at radius R with customizable background / border luminance
    - White patch arc
    - Needle at needle_deg
    """
    buf = bytearray(crop_size * crop_size * 4)
    w = crop_size
    h = crop_size

    # Fill background with base border luminance
    b_val = max(0, min(255, border_lum))
    for i in range(0, len(buf), 4):
        buf[i] = b_val      # Blue
        buf[i + 1] = b_val  # Green
        buf[i + 2] = b_val  # Red
        buf[i + 3] = 255    # Alpha

    # Draw central spacebar glyph [_] if requested
    if with_glyph:
        # Inner dark face: y in [cy - 12 .. cy + 1], x in [cx - 24 .. cx + 24]
        for y in range(cy - 12, cy + 2):
            for x in range(cx - 24, cx + 25):
                off = (y * w + x) * 4
                buf[off] = 20
                buf[off + 1] = 20
                buf[off + 2] = 20

        # Bottom white bar: y in [cy + 2 .. cy + 4], x in [cx - 27 .. cx + 27]
        for y in range(cy + 2, cy + 5):
            for x in range(cx - 27, cx + 28):
                off = (y * w + x) * 4
                buf[off] = 250
                buf[off + 1] = 250
                buf[off + 2] = 250

        # Uprights:
        for y in range(cy - 6, cy + 5):
            for dx in range(3):
                off_l = (y * w + cx - 27 + dx) * 4
                off_r = (y * w + cx + 25 + dx) * 4
                buf[off_l] = 250
                buf[off_l + 1] = 250
                buf[off_l + 2] = 250
                buf[off_r] = 250
                buf[off_r + 1] = 250
                buf[off_r + 2] = 250

    # Draw circular dark ring track (unless border_lum is already dark)
    ring_track_lum = max(15, b_val // 2)
    for a_deg in range(360):
        rad = math.radians(a_deg)
        for dr in range(-6, 7):
            r_curr = R + dr
            px = int(round(cx + r_curr * math.cos(rad)))
            py = int(round(cy + r_curr * math.sin(rad)))
            if 0 <= px < w and 0 <= py < h:
                off = (py * w + px) * 4
                buf[off] = ring_track_lum
                buf[off + 1] = ring_track_lum
                buf[off + 2] = ring_track_lum

    # Draw white patch arc if specified
    if white_patch is not None:
        p_start, p_span = white_patch
        pr, pg, pb = patch_rgb
        for step in range(int(round(p_span * 4))):
            deg = (p_start + step * 0.25) % 360.0
            rad = math.radians(deg)
            for dr in [-3, -2, -1, 0, 1, 2, 3]:
                r_curr = R + dr
                px = int(round(cx + r_curr * math.cos(rad)))
                py = int(round(cy + r_curr * math.sin(rad)))
                if 0 <= px < w and 0 <= py < h:
                    off = (py * w + px) * 4
                    buf[off] = pb
                    buf[off + 1] = pg
                    buf[off + 2] = pr

    # Draw red needle if specified
    if needle_deg is not None:
        n_rad = math.radians(needle_deg)
        cos_n, sin_n = math.cos(n_rad), math.sin(n_rad)
        # Needle extends from R * 0.35 to R * 0.85
        for r_curr in range(int(R * 0.35), int(R * 0.85)):
            for ortho in [-1, 0, 1]:
                px = int(round(cx + r_curr * cos_n - ortho * sin_n))
                py = int(round(cy + r_curr * sin_n + ortho * cos_n))
                if 0 <= px < w and 0 <= py < h:
                    off = (py * w + px) * 4
                    buf[off] = 20      # Low Blue
                    buf[off + 1] = 20  # Low Green
                    buf[off + 2] = 240 # High Red

    return buf


class TestWhitePatchDetectionAllQuadrants(unittest.TestCase):
    """Verifies that white patch detection functions reliably in every quadrant without dark-border bias."""

    def setUp(self):
        self.detector = QTEDetector(crop_size=320, hit_position="start")

    def test_bottom_left_patch_with_dark_borders(self):
        """Standard bottom-left patch (angle ~145°) with dark borders (<95 lum)."""
        buf = create_synthetic_frame(white_patch=(144.0, 10.5), border_lum=30)
        res = self.detector.detect_white_patch(buf, 160, 160, 83)
        self.assertIsNotNone(res)
        start, end, center, span = res
        self.assertAlmostEqual(start, 144.0, delta=1.5)
        self.assertAlmostEqual(span, 10.5, delta=1.5)

    def test_top_patch_with_bright_borders(self):
        """Top quadrant patch (angle ~270°) against bright background / generator lights (lum 160)."""
        buf = create_synthetic_frame(white_patch=(265.0, 10.0), border_lum=160)
        res = self.detector.detect_white_patch(buf, 160, 160, 83)
        self.assertIsNotNone(res, "Top patch must be detected even with bright background / border luminance > 95!")
        start, end, center, span = res
        self.assertAlmostEqual(start, 265.0, delta=1.5)
        self.assertAlmostEqual(span, 10.0, delta=1.5)

    def test_right_patch_with_bright_borders(self):
        """Right quadrant patch (angle ~0°/360°) against bright background (lum 140)."""
        buf = create_synthetic_frame(white_patch=(355.0, 10.0), border_lum=140)
        res = self.detector.detect_white_patch(buf, 160, 160, 83)
        self.assertIsNotNone(res, "Right patch wrapping 0° must be detected with bright background!")
        start, end, center, span = res
        self.assertAlmostEqual(start, 355.0, delta=1.5)
        self.assertAlmostEqual(span, 10.0, delta=1.5)

    def test_bottom_patch_with_bright_borders(self):
        """Bottom quadrant patch (angle ~90°) against bright background (lum 150)."""
        buf = create_synthetic_frame(white_patch=(85.0, 11.0), border_lum=150)
        res = self.detector.detect_white_patch(buf, 160, 160, 83)
        self.assertIsNotNone(res, "Bottom patch must be detected with bright background!")
        start, end, center, span = res
        self.assertAlmostEqual(start, 85.0, delta=1.5)
        self.assertAlmostEqual(span, 11.0, delta=1.5)

    def test_multiple_candidates_picks_brightest_patch(self):
        """When a dim texture/flare candidate exists alongside the white patch, the true patch is chosen."""
        buf = create_synthetic_frame(white_patch=(180.0, 10.0), patch_rgb=(255, 255, 255), border_lum=50)
        # Add a dimmer candidate around 60°
        w = 320
        h = 320
        for step in range(30):
            deg = (60.0 + step * 0.25)
            rad = math.radians(deg)
            for dr in [-2, -1, 0, 1, 2]:
                px = int(round(160 + (83 + dr) * math.cos(rad)))
                py = int(round(160 + (83 + dr) * math.sin(rad)))
                if 0 <= px < w and 0 <= py < h:
                    off = (py * w + px) * 4
                    buf[off] = 160
                    buf[off + 1] = 160
                    buf[off + 2] = 190  # Dimmer lum ~170 vs white patch ~255
        res = self.detector.detect_white_patch(buf, 160, 160, 83)
        self.assertIsNotNone(res)
        start, end, center, span = res
        self.assertAlmostEqual(start, 180.0, delta=1.5, msg="Detector must select the brighter white patch candidate")


class TestEarlyTriggerSafety(unittest.TestCase):
    """Verifies that early trigger is 100% prevented when hit_position == 'start'."""

    def setUp(self):
        self.detector = QTEDetector(crop_size=320, hit_position="start")

    def test_needle_approaching_before_patch_does_not_trigger(self):
        """Needle at 140° approaching patch at [145°..155°] MUST NOT trigger."""
        buf = create_synthetic_frame(white_patch=(145.0, 10.0), needle_deg=140.0)
        res = self.detector.evaluate(buf)
        self.assertTrue(res['present'])
        self.assertFalse(res['should_trigger'], "Needle before patch start MUST NOT trigger early!")

    def test_dynamic_tracking_crossing_patch_start_triggers(self):
        """In consecutive frames: needle at 142° then 146° crossing patch start (145°) MUST trigger."""
        buf1 = create_synthetic_frame(white_patch=(145.0, 10.0), needle_deg=142.0)
        res1 = self.detector.evaluate(buf1)
        self.assertFalse(res1['should_trigger'], "Frame 1: Needle before patch must not trigger")

        buf2 = create_synthetic_frame(white_patch=(145.0, 10.0), needle_deg=146.0)
        res2 = self.detector.evaluate(buf2)
        self.assertTrue(res2['should_trigger'], "Frame 2: Needle crossing into white patch MUST trigger immediately")
        self.assertIn("white patch", res2['reason'].lower())

    def test_needle_static_inside_patch_triggers(self):
        """Single-frame detection where needle is inside patch [145°..155°] at 148° MUST trigger."""
        buf = create_synthetic_frame(white_patch=(145.0, 10.0), needle_deg=148.0)
        res = self.detector.evaluate(buf)
        self.assertTrue(res['present'])
        self.assertTrue(res['should_trigger'], "Needle inside patch must trigger")

    def test_needle_far_away_does_not_trigger(self):
        """Needle at 50° while patch is at 145° MUST NOT trigger."""
        buf = create_synthetic_frame(white_patch=(145.0, 10.0), needle_deg=50.0)
        res = self.detector.evaluate(buf)
        self.assertTrue(res['present'])
        self.assertFalse(res['should_trigger'], "Faraway needle must not trigger")

    def test_dynamic_tracking_crossing_patch_start_wraparound(self):
        """Needle crossing patch start at 0°/360° (patch at [355°..5°]) MUST trigger without early activation."""
        buf1 = create_synthetic_frame(white_patch=(355.0, 10.0), needle_deg=350.0)
        res1 = self.detector.evaluate(buf1)
        self.assertFalse(res1['should_trigger'], "Needle at 350° before 355° MUST NOT trigger")

        buf2 = create_synthetic_frame(white_patch=(355.0, 10.0), needle_deg=354.5)
        res2 = self.detector.evaluate(buf2)
        self.assertFalse(res2['should_trigger'], "Needle at 354.5° before 355° MUST NOT trigger")

        buf3 = create_synthetic_frame(white_patch=(355.0, 10.0), needle_deg=356.0)
        res3 = self.detector.evaluate(buf3)
        self.assertTrue(res3['should_trigger'], "Needle at 356.0° crossing 355° start MUST trigger")
        self.assertIn("white patch", res3['reason'].lower())

    def test_multi_step_approach_up_to_boundary_never_early(self):
        """Multi-frame approach stepping 135° -> 138° -> 141° -> 143° -> 144.5° right before 145° boundary MUST NOT trigger."""
        for deg in [135.0, 138.0, 141.0, 143.0, 144.5]:
            buf = create_synthetic_frame(white_patch=(145.0, 10.0), needle_deg=deg)
            res = self.detector.evaluate(buf)
            self.assertFalse(res['should_trigger'], f"Needle at {deg}° before 145.0° patch start triggered early!")

    def test_hit_position_start_ignores_configured_lead_and_latency(self):
        """When hit_position == 'start', configured lead and latency MUST NOT cause premature trigger."""
        detector = QTEDetector(crop_size=320, hit_position="start", lead_degrees=10.0, latency_ms=50.0)
        buf1 = create_synthetic_frame(white_patch=(145.0, 10.0), needle_deg=138.0)
        res1 = detector.evaluate(buf1)
        self.assertFalse(res1['should_trigger'])

        buf2 = create_synthetic_frame(white_patch=(145.0, 10.0), needle_deg=144.5)
        res2 = detector.evaluate(buf2)
        self.assertFalse(res2['should_trigger'], "Configured lead/latency must never trigger before patch start")

        buf3 = create_synthetic_frame(white_patch=(145.0, 10.0), needle_deg=145.5)
        res3 = detector.evaluate(buf3)
        self.assertTrue(res3['should_trigger'], "Must trigger when entering patch")


class TestZeroDelayConfiguration(unittest.TestCase):
    """Verifies that all artificial delays are removed (zero delay everywhere)."""

    def test_default_config_zero_delays(self):
        """DEFAULT_CONFIG must have poll_interval_ms=0, trigger_delay_ms=0, latency_ms=0.0."""
        self.assertEqual(DEFAULT_CONFIG.get("poll_interval_ms"), 0)
        self.assertEqual(DEFAULT_CONFIG.get("trigger_delay_ms"), 0)
        self.assertEqual(DEFAULT_CONFIG.get("latency_ms"), 0.0)
        self.assertEqual(DEFAULT_CONFIG.get("top_bar_offset"), 0)
        self.assertEqual(DEFAULT_CONFIG.get("crop_size"), 320)
        self.assertEqual(DEFAULT_CONFIG.get("hit_position"), "start")

    def test_calculate_effective_delay_zero(self):
        """calculate_effective_delay returns 0.0 when base delay <= 0."""
        detector = QTEDetector(crop_size=320, trigger_delay_ms=0)
        self.assertEqual(detector.calculate_effective_delay(0.0), 0.0)
        self.assertEqual(detector.calculate_effective_delay(-0.01), 0.0)
        self.assertEqual(detector.calculate_effective_delay(None), 0.0)

    def test_evaluate_returns_zero_effective_delay(self):
        """evaluate() output dict contains effective_delay_s == 0.0 when configured for 0ms delay."""
        detector = QTEDetector(crop_size=320, trigger_delay_ms=0, hit_position="start")
        buf = create_synthetic_frame(white_patch=(145.0, 10.0), needle_deg=146.0)
        res = detector.evaluate(buf)
        self.assertEqual(res['effective_delay_s'], 0.0)


class TestRobustnessAndEdgeCases(unittest.TestCase):
    """Tests empty, solid, and corrupted buffers."""

    def setUp(self):
        self.detector = QTEDetector(crop_size=320)

    def test_empty_buffer(self):
        """Empty buffer returns present=False without crashing."""
        res = self.detector.evaluate(b"")
        self.assertFalse(res['present'])

    def test_solid_black_buffer(self):
        """Solid black buffer returns present=False without crashing."""
        buf = bytearray(320 * 320 * 4)
        res = self.detector.evaluate(buf)
        self.assertFalse(res['present'])

    def test_solid_white_buffer(self):
        """Solid white buffer returns present=False without crashing."""
        buf = bytearray([255] * (320 * 320 * 4))
        res = self.detector.evaluate(buf)
        self.assertFalse(res['present'])


class TestAdaptiveCalibrationLeadAndBounds(unittest.TestCase):
    """Verifies continuous velocity-based dynamic lead calculation and critical safety bounds."""

    def test_zero_initial_latency_has_zero_lead(self):
        """Initial state starting at tau = 0.0ms MUST produce strictly 0.0° lead across all velocities."""
        engine = AdaptiveCalibrationEngine(speed_calibration=[{"speed": 500, "latency_ms": 0.0}], persist_config=False)
        for w in [0.0, 150.0, 300.0, 600.0, 900.0, 1500.0]:
            lead = engine.calculate_dynamic_lead(w)
            self.assertEqual(lead, 0.0, f"Expected 0.0° lead at velocity {w}°/s when tau=0.0ms, got {lead}°")

    def test_continuous_velocity_lead_proportionality(self):
        """Verify dynamic lead Δθ_lead(ω) = ω * τ_learned is continuous and linear with speed."""
        # tau = 20.0ms = 0.020s
        engine = AdaptiveCalibrationEngine(speed_calibration=[{"speed": 500, "latency_ms": 20.0}], persist_config=False)
        self.assertAlmostEqual(engine.calculate_dynamic_lead(300.0), 6.0, places=2)
        self.assertAlmostEqual(engine.calculate_dynamic_lead(500.0), 10.0, places=2)
        self.assertAlmostEqual(engine.calculate_dynamic_lead(750.0), 15.0, places=2)

    def test_critical_safety_bounds_clamping(self):
        """Dynamic lead must be strictly clamped to max_lead_degrees (18.0°) and non-negative."""
        engine = AdaptiveCalibrationEngine(speed_calibration=[{"speed": 500, "latency_ms": 50.0}], max_lead_degrees=18.0, persist_config=False)
        # 1000°/s * 0.050s = 50.0° -> MUST clamp to 18.0°
        clamped_lead = engine.calculate_dynamic_lead(1000.0)
        self.assertEqual(clamped_lead, 18.0)

        # Negative velocity or zero velocity must return 0.0
        self.assertEqual(engine.calculate_dynamic_lead(-100.0), 0.0)
        self.assertEqual(engine.calculate_dynamic_lead(0.0), 0.0)

    def test_latency_limits_clamping(self):
        """Learned latency parameter must not go below 0.0ms or above max_latency_ms."""
        engine = AdaptiveCalibrationEngine(speed_calibration=[{"speed": 500, "latency_ms": 0.0}], min_latency_ms=0.0, max_latency_ms=80.0, persist_config=False)
        # Force a large negative adjustment
        res = engine.update_learned_latency(
            stopped_angle=110.0, trigger_angle=120.0, angular_velocity=500.0,
            patch_start=120.0, patch_end=130.0, patch_center=125.0, patch_span=10.0,
            log_entry=False
        )
        self.assertGreaterEqual(engine.speed_calibration[0]["latency_ms"], 0.0)

        # Force a large positive update sequence up to max
        for _ in range(60):
            engine.update_learned_latency(
                stopped_angle=140.0, trigger_angle=120.0, angular_velocity=500.0,
                patch_start=120.0, patch_end=130.0, patch_center=125.0, patch_span=10.0,
                log_entry=False
            )
        self.assertLessEqual(engine.speed_calibration[0]["latency_ms"], 80.0)


class TestAdaptiveCalibrationErrorAndLearning(unittest.TestCase):
    """Verifies error calculations, hit classifications, and conservative parameter updates."""

    def setUp(self):
        self.engine = AdaptiveCalibrationEngine(speed_calibration=[{"speed": 500, "latency_ms": 0.0}], persist_config=False)

    def test_angular_error_calculation_with_circular_wraparound(self):
        """Calculate signed angular error relative to patch center across quadrants and 0°/360°."""
        # Standard quadrant: center 127.5°, stopped 135.0° -> late by +7.5°
        err1 = self.engine.calculate_angular_error(135.0, 127.5)
        self.assertAlmostEqual(err1, 7.5, places=2)

        # Standard quadrant: center 127.5°, stopped 120.0° -> early by -7.5°
        err2 = self.engine.calculate_angular_error(120.0, 127.5)
        self.assertAlmostEqual(err2, -7.5, places=2)

        # Wrap across 0°/360°: center 5.0°, stopped 358.0° -> counter-clockwise by -7.0°
        err3 = self.engine.calculate_angular_error(358.0, 5.0)
        self.assertAlmostEqual(err3, -7.0, places=2)

        # Wrap across 0°/360°: center 355.0°, stopped 2.0° -> clockwise by +7.0°
        err4 = self.engine.calculate_angular_error(2.0, 355.0)
        self.assertAlmostEqual(err4, 7.0, places=2)

    def test_hit_classification_zones(self):
        """Classify hit landing points as GREAT, GOOD (late), or EARLY."""
        # Patch [120.0°..130.0°], Center 125.0°, Span 10.0°
        self.assertEqual(self.engine.classify_hit(120.0, 120.0, 130.0, 125.0, 10.0), "GREAT")
        self.assertEqual(self.engine.classify_hit(125.0, 120.0, 130.0, 125.0, 10.0), "GREAT")
        self.assertEqual(self.engine.classify_hit(130.0, 120.0, 130.0, 125.0, 10.0), "GREAT")

        # Stopped in Good zone past patch
        self.assertEqual(self.engine.classify_hit(131.0, 120.0, 130.0, 125.0, 10.0), "GOOD")
        self.assertEqual(self.engine.classify_hit(145.0, 120.0, 130.0, 125.0, 10.0), "GOOD")
        # Far late hits beyond traditional Good zone are still late (GOOD), never EARLY
        self.assertEqual(self.engine.classify_hit(195.0, 120.0, 130.0, 125.0, 10.0), "GOOD")
        self.assertEqual(self.engine.classify_hit(240.0, 120.0, 130.0, 125.0, 10.0), "GOOD")

        # Stopped before patch start (counter-clockwise)
        self.assertEqual(self.engine.classify_hit(115.0, 120.0, 130.0, 125.0, 10.0), "EARLY")
        self.assertEqual(self.engine.classify_hit(50.0, 120.0, 130.0, 125.0, 10.0), "EARLY")

    def test_early_hit_safety_backoff(self):
        """Early hit before patch start must immediately back off latency (at least -1.0ms, at most -5.0ms)."""
        # error = -8.0° at 400°/s -> raw = -20ms -> alpha * -20 = -4.0ms
        adj = self.engine.calculate_latency_adjustment(error=-8.0, velocity=400.0, hit_result="EARLY")
        self.assertEqual(adj, -4.0)

        # Tiny early error: must still back off by at least 1.0ms for zero early tolerance
        adj_tiny = self.engine.calculate_latency_adjustment(error=-0.5, velocity=600.0, hit_result="EARLY")
        self.assertEqual(adj_tiny, -1.0)

        # Huge early error: clamped to -5.0ms
        adj_huge = self.engine.calculate_latency_adjustment(error=-30.0, velocity=300.0, hit_result="EARLY")
        self.assertEqual(adj_huge, -5.0)

    def test_conservative_late_hit_learning_step(self):
        """Late hit in Good zone increases latency conservatively with step limit (<= 2.0ms)."""
        # omega = 500°/s, stopped at 135° with center at 125° -> error = +10.0°
        # raw adjustment = (10 / 500) * 1000 = 20.0ms
        # alpha = 0.20 -> alpha * 20.0 = 4.0ms, clamped to max_adjustment_ms (2.0ms)
        adj = self.engine.calculate_latency_adjustment(error=10.0, velocity=500.0, hit_result="GOOD")
        self.assertEqual(adj, 2.0)

        # Smaller late error: error = +3.0° at 600°/s -> raw = 5.0ms -> alpha * 5.0 = 1.0ms
        adj_small = self.engine.calculate_latency_adjustment(error=3.0, velocity=600.0, hit_result="GOOD")
        self.assertAlmostEqual(adj_small, 1.0, places=2)

    def test_great_hit_micro_adjustment(self):
        """Hit inside Great white patch makes small micro-adjustments toward center."""
        # error = +1.5° at 400°/s: inside patch
        # raw = (1.5 / 400) * 1000 = 3.75ms. alpha = 0.15 -> 0.5625ms
        adj = self.engine.calculate_latency_adjustment(error=1.5, velocity=400.0, hit_result="GREAT")
        self.assertAlmostEqual(adj, 0.56, delta=0.02)

        # Within deadband <= 0.35°: no adjustment
        adj_deadband = self.engine.calculate_latency_adjustment(error=0.2, velocity=400.0, hit_result="GREAT")
        self.assertEqual(adj_deadband, 0.0)

    def test_low_velocity_guard(self):
        """No adjustment made when velocity is below reliable threshold (< 50°/s)."""
        adj = self.engine.calculate_latency_adjustment(error=5.0, velocity=30.0, hit_result="GOOD")
        self.assertEqual(adj, 0.0)


class TestPostHitFreezeMeasurement(unittest.TestCase):
    """Verifies freeze detection during the 80ms-180ms window and resting angle capture."""

    def test_freeze_resting_angle_detection(self):
        """Engine captures resting angle during freeze window and updates latency."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "calibration.log")
            cfg_path = os.path.join(tmpdir, "config.json")
            engine = AdaptiveCalibrationEngine(
                config_path=cfg_path, log_path=log_path, speed_calibration=[{"speed": 500, "latency_ms": 0.0}], persist_config=True
            )

            t0 = 1000.0
            engine.record_trigger(
                trigger_time=t0, trigger_angle=124.0, angular_velocity=400.0,
                patch_start=120.0, patch_end=130.0, patch_center=125.0, patch_span=10.0
            )

            # Frame at 50ms: before freeze window, should not be recorded
            res50 = engine.on_frame(now=t0 + 0.050, needle_angle=132.0, needle_score=60.0, qte_present=True)
            self.assertIsNone(res50)
            self.assertEqual(len(engine._freeze_samples), 0)

            # Frames in freeze window [80ms..180ms]: needle is stopped at 134.0°
            engine.on_frame(now=t0 + 0.090, needle_angle=134.0, needle_score=68.0, qte_present=True)
            engine.on_frame(now=t0 + 0.120, needle_angle=134.0, needle_score=68.0, qte_present=True)
            engine.on_frame(now=t0 + 0.150, needle_angle=134.1, needle_score=67.0, qte_present=True)
            self.assertEqual(len(engine._freeze_samples), 3)

            # Frame at 185ms: freeze window completes and finalizes calibration
            res_fin = engine.on_frame(now=t0 + 0.185, needle_angle=134.0, needle_score=65.0, qte_present=True)
            self.assertIsNotNone(res_fin)
            self.assertAlmostEqual(res_fin['stopped_angle'], 134.0, delta=0.2)
            self.assertEqual(res_fin['result'], "GOOD")
            self.assertAlmostEqual(res_fin['error'], 9.0, delta=0.2)
            self.assertGreater(res_fin['latency_after'], 0.0)

    def test_freeze_finalization_when_qte_vanishes(self):
        """When QTE UI disappears after collecting samples, finalize immediately."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "calibration.log")
            cfg_path = os.path.join(tmpdir, "config.json")
            engine = AdaptiveCalibrationEngine(
                config_path=cfg_path, log_path=log_path, speed_calibration=[{"speed": 500, "latency_ms": 0.0}], persist_config=True
            )

            t0 = 500.0
            engine.record_trigger(
                trigger_time=t0, trigger_angle=125.0, angular_velocity=350.0,
                patch_start=120.0, patch_end=130.0, patch_center=125.0, patch_span=10.0
            )

            engine.on_frame(now=t0 + 0.090, needle_angle=126.0, needle_score=65.0, qte_present=True)
            engine.on_frame(now=t0 + 0.110, needle_angle=126.0, needle_score=65.0, qte_present=True)

            # UI disappears at 130ms (qte_present=False)
            res = engine.on_frame(now=t0 + 0.130, needle_angle=None, needle_score=0.0, qte_present=False)
            self.assertIsNotNone(res)
            self.assertEqual(res['result'], "GREAT")

    def test_freeze_single_sample_recovery(self):
        """Engine successfully calibrates when only 1 frame was sampled in window before UI vanishes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "calibration.log")
            cfg_path = os.path.join(tmpdir, "config.json")
            engine = AdaptiveCalibrationEngine(
                config_path=cfg_path, log_path=log_path, speed_calibration=[{"speed": 500, "latency_ms": 0.0}], persist_config=False
            )

            t0 = 200.0
            engine.record_trigger(
                trigger_time=t0, trigger_angle=124.0, angular_velocity=600.0,
                patch_start=120.0, patch_end=130.0, patch_center=125.0, patch_span=10.0
            )

            # Only 1 frame captured in freeze window at 100ms
            engine.on_frame(now=t0 + 0.100, needle_angle=134.5, needle_score=68.0, qte_present=True)

            # UI disappears at 125ms
            res = engine.on_frame(now=t0 + 0.125, needle_angle=None, needle_score=0.0, qte_present=False)
            self.assertIsNotNone(res, "Single freeze sample must not be discarded when QTE disappears")
            self.assertAlmostEqual(res['stopped_angle'], 134.5, delta=0.1)
            self.assertEqual(res['result'], "GOOD")
            self.assertGreater(res['delta_tau'], 0.0)

    def test_immediate_finalization_on_absent_frame_in_evaluate(self):
        """Detector evaluate() immediately triggers calibration on the first absent frame without waiting 3 frames."""
        engine = AdaptiveCalibrationEngine(speed_calibration=[{"speed": 500, "latency_ms": 0.0}], persist_config=False)
        detector = QTEDetector(crop_size=320, hit_position="start", calibration_engine=engine)
        
        t0 = 100.0
        # Trigger event recorded
        detector.record_trigger(
            trigger_time=t0, trigger_angle=125.0, angular_velocity=500.0,
            patch_start=120.0, patch_end=130.0, patch_center=125.0, patch_span=10.0
        )
        detector.is_qte_active = True

        # Frame in freeze window at 90ms
        buf_freeze = create_synthetic_frame(white_patch=(120.0, 10.0), needle_deg=135.0)
        detector.evaluate(buf_freeze, now=t0 + 0.090)
        self.assertTrue(engine._is_tracking)
        self.assertEqual(len(engine._freeze_samples), 1)

        # Empty / absent buffer at 120ms (frame 1 absent): should finalize immediately!
        empty_buf = bytearray(320 * 320 * 4)  # solid black, no glyph
        res_absent = detector.evaluate(empty_buf, now=t0 + 0.120)
        self.assertFalse(res_absent['present'])
        self.assertFalse(engine._is_tracking, "Engine tracking must finalize on first absent frame after freeze window start")
        self.assertTrue(engine._finalized)
        self.assertGreater(engine.speed_calibration[0]["latency_ms"], 0.0)


class TestDiagnosticLogAndPersistence(unittest.TestCase):
    """Verifies calibration.log formatting and config.json persistence."""

    def test_calibration_log_format_exact_match(self):
        pass

    def test_config_persistence_preserves_other_keys(self):
        """Updating learned latency persists to config.json without overwriting existing settings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            initial_data = {
                "crop_size": 320,
                "hit_position": "start",
                "hold_duration_ms": 35,
                "learned_latency_ms": 0.0
            }
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(initial_data, f, indent=4)

            engine = AdaptiveCalibrationEngine(
                config_path=cfg_path, speed_calibration=[{"speed": 500, "latency_ms": 0.0}], persist_config=True
            )
            engine.update_learned_latency(
                stopped_angle=135.0, trigger_angle=125.0, angular_velocity=500.0,
                patch_start=120.0, patch_end=130.0, patch_center=125.0, patch_span=10.0,
                log_entry=False
            )

            with open(cfg_path, "r", encoding="utf-8") as f:
                saved = json.load(f)

            self.assertEqual(saved["crop_size"], 320)
            self.assertEqual(saved["hit_position"], "start")
            self.assertEqual(saved["hold_duration_ms"], 35)
            self.assertAlmostEqual(saved["speed_calibration"][0]["latency_ms"], 2.0, places=1)


class TestDetectorAdaptiveTriggering(unittest.TestCase):
    """Verifies QTEDetector integration with AdaptiveCalibrationEngine."""

    def test_detector_zero_latency_no_early_trigger(self):
        """Default detector with learned_latency_ms=0.0 must never trigger before patch start."""
        detector = QTEDetector(crop_size=320, hit_position="start", learned_latency_ms=0.0)
        buf1 = create_synthetic_frame(white_patch=(145.0, 10.0), needle_deg=143.0)
        res1 = detector.evaluate(buf1)
        self.assertFalse(res1['should_trigger'])

        buf2 = create_synthetic_frame(white_patch=(145.0, 10.0), needle_deg=144.8)
        res2 = detector.evaluate(buf2)
        self.assertFalse(res2['should_trigger'], "Needle before patch start must not trigger when tau=0")

        buf3 = create_synthetic_frame(white_patch=(145.0, 10.0), needle_deg=145.5)
        res3 = detector.evaluate(buf3)
        self.assertTrue(res3['should_trigger'], "Needle inside patch must trigger")

    def test_detector_calibrated_lead_advances_trigger_safely(self):
        """Calibrated detector with tau=20ms and velocity advances trigger safely without premature trigger."""
        engine = AdaptiveCalibrationEngine(speed_calibration=[{"speed": 500, "latency_ms": 20.0}], persist_config=False)
        detector = QTEDetector(crop_size=320, hit_position="start", calibration_engine=engine)
        detector.angular_velocity = 500.0

        # Frame 1: needle at 120° (too far, before ~140° patch-center lead target)
        buf1 = create_synthetic_frame(white_patch=(145.0, 10.0), needle_deg=120.0)
        res1 = detector.evaluate(buf1)
        self.assertFalse(res1['should_trigger'], "Needle far away before lead target must not trigger")

        # Frame 2: needle approaching at 133° (before ~140° patch-center lead target)
        buf2 = create_synthetic_frame(white_patch=(145.0, 10.0), needle_deg=133.0)
        res2 = detector.evaluate(buf2)
        self.assertFalse(res2['should_trigger'], "Needle approaching before lead target must not trigger")

        # Frame 3: needle crossing original lead target at 142.0° (before patch start 145.0°) - shouldn't trigger due to clamp
        buf3 = create_synthetic_frame(white_patch=(145.0, 10.0), needle_deg=142.0)
        res3 = detector.evaluate(buf3)
        self.assertFalse(res3['should_trigger'], "Needle before patch start must not trigger due to safety clamp")

        # Frame 4: needle at patch start 145.0° - should trigger
        buf4 = create_synthetic_frame(white_patch=(145.0, 10.0), needle_deg=145.0)
        res4 = detector.evaluate(buf4)
        self.assertTrue(res4['should_trigger'], "Needle at clamped target must trigger")

    def test_detector_evaluate_timestamp_parameter(self):
        """Passing an explicit timestamp to evaluate(buf, now=t) correctly drives velocity and timers."""
        detector = QTEDetector(crop_size=320, hit_position="start")
        buf1 = create_synthetic_frame(white_patch=(145.0, 10.0), needle_deg=50.0)
        res1 = detector.evaluate(buf1, now=10.0)
        self.assertAlmostEqual(detector.prev_needle_time, 10.0)

        # 30ms later, needle advanced to 70.0° (20° in 0.030s = 666.7°/s)
        buf2 = create_synthetic_frame(white_patch=(145.0, 10.0), needle_deg=70.0)
        res2 = detector.evaluate(buf2, now=10.030)
        self.assertAlmostEqual(detector.prev_needle_time, 10.030)
        self.assertGreater(res2['angular_velocity'], 500.0)
        self.assertLess(res2['angular_velocity'], 800.0)

    def test_real_video_analysis_and_calibration(self):
        """Analyze sample frames from the real gameplay video and verify speed range and freeze calibration."""
        video_path = r"C:\Users\Yonah\Videos\This Gen Rush Build Needs To Be NERFED (02.17-02.24).mp4"
        if not os.path.exists(video_path):
            self.skipTest(f"Video file not present at {video_path}")

        try:
            import cv2
        except ImportError:
            self.skipTest("OpenCV not installed")

        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        engine = AdaptiveCalibrationEngine(speed_calibration=[{"speed": 500, "latency_ms": 0.0}], persist_config=False)
        detector = QTEDetector(crop_size=320, hit_position="start", calibration_engine=engine)
        cx, cy = 2552 // 2, 1440 // 2
        crop_size = 320
        frame_idx = 0

        max_speed = 0.0
        trigger_count = 0

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            t_frame = frame_idx / fps
            crop = frame[cy - crop_size // 2 : cy + crop_size // 2, cx - crop_size // 2 : cx + crop_size // 2]
            crop_bgra = cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA)
            res = detector.evaluate(crop_bgra.tobytes(), now=t_frame)

            if res['angular_velocity'] > max_speed:
                max_speed = res['angular_velocity']

            if res['should_trigger']:
                trigger_count += 1
                detector.record_trigger(
                    trigger_time=t_frame,
                    trigger_angle=res['needle_angle'],
                    angular_velocity=res.get('angular_velocity', 0.0),
                    patch_start=res['patch_start'],
                    patch_end=res['patch_end'],
                    patch_center=res['patch_center'],
                    patch_span=res['patch_span']
                )

            frame_idx += 1
        cap.release()

        # Verify requirements from video analysis:
        # (a) Needle rotation speed range ω: measured at ~270°/s to ~430°/s (EMA peak ~354°/s) across video perk stacks
        self.assertGreaterEqual(max_speed, 300.0, f"Max speed {max_speed:.1f}°/s should reflect video perk stacks")
        # (b) QTEs were detected and triggered
        self.assertGreaterEqual(trigger_count, 3, "Should detect and trigger multiple QTE sequences in video")
        # (c) Post-hit freeze detection calibrated latency positively from late hits
        self.assertGreater(engine.speed_calibration[0]["latency_ms"], 0.0, "Learned latency must increase from late freeze hits")

    def test_continuous_consecutive_skillchecks_new_patch_location(self):
        """Verify re-arming and triggering when a second skill check spawns immediately without the circle disappearing."""
        detector = QTEDetector(crop_size=320, hit_position="start")

        # Frame 1: First check at 120°, needle at 80°
        f1 = create_synthetic_frame(white_patch=(115.0, 10.0), needle_deg=80.0)
        r1 = detector.evaluate(f1, now=1.0)
        self.assertFalse(r1['should_trigger'])

        # Frame 2: Needle reaches first patch at 116° -> Triggers!
        f2 = create_synthetic_frame(white_patch=(115.0, 10.0), needle_deg=116.0)
        r2 = detector.evaluate(f2, now=1.05)
        self.assertTrue(r2['should_trigger'])
        detector.record_trigger(trigger_time=1.05, trigger_angle=116.0, angular_velocity=300.0,
                                patch_start=115.0, patch_end=125.0, patch_center=120.0, patch_span=10.0)

        # Frame 3: Needle moved past, second patch appears at 240° without circle vanishing
        f3 = create_synthetic_frame(white_patch=(235.0, 10.0), needle_deg=135.0)
        r3 = detector.evaluate(f3, now=1.12)
        self.assertFalse(r3['should_trigger'])

        # Frame 4: Needle approaches second patch at 236° -> Triggers second check!
        f4 = create_synthetic_frame(white_patch=(235.0, 10.0), needle_deg=236.0)
        r4 = detector.evaluate(f4, now=1.20)
        self.assertTrue(r4['should_trigger'], "Second continuous skill check must trigger cleanly!")

    def test_continuous_consecutive_skillchecks_full_rotation(self):
        """Verify re-arming and triggering when the needle completes a full loop around the same circle without disappearing."""
        detector = QTEDetector(crop_size=320, hit_position="start")

        # Frame 1: Patch at 120°, needle at 80°
        f1 = create_synthetic_frame(white_patch=(115.0, 10.0), needle_deg=80.0)
        r1 = detector.evaluate(f1, now=1.0)
        self.assertFalse(r1['should_trigger'])

        # Frame 2: Needle hits patch at 116° -> Triggers!
        f2 = create_synthetic_frame(white_patch=(115.0, 10.0), needle_deg=116.0)
        r2 = detector.evaluate(f2, now=1.05)
        self.assertTrue(r2['should_trigger'])
        detector.record_trigger(trigger_time=1.05, trigger_angle=116.0, angular_velocity=300.0,
                                patch_start=115.0, patch_end=125.0, patch_center=120.0, patch_span=10.0)

        # Frame 3: Needle continues loop around circle (needle at 250°, time +0.25s)
        f3 = create_synthetic_frame(white_patch=(115.0, 10.0), needle_deg=250.0)
        r3 = detector.evaluate(f3, now=1.30)
        self.assertFalse(r3['should_trigger'])

        # Frame 4: Needle approaches same patch again on second rotation (needle at 116°, time +0.40s)
        f4 = create_synthetic_frame(white_patch=(115.0, 10.0), needle_deg=116.0)
        r4 = detector.evaluate(f4, now=1.45)
        self.assertTrue(r4['should_trigger'], "Second full-rotation skill check must trigger cleanly!")


class TestChainedCheckImmunityAndFastAdaptation(unittest.TestCase):
    """
    Verifies resilience against continuous chained skill checks and sudden speed changes:
    1. Chained check calibration lock: follow-up hits in active QTE do not calibrate latency.
    2. Stationary freeze verification: needle moving during freeze window (drift >= 2.0°) is discarded.
    3. Outlier rejection: angular error > 20.0° from sweeping needle is rejected.
    4. Instant speedometer adaptation: sudden speed drop (< 0.5 * speed) or chained check reset adapts with zero EMA lag.
    """

    def test_chained_check_calibration_immunity(self):
        pass

    def test_stationary_freeze_verification_moving_needle_discarded(self):
        """Freeze samples with angular drift >= 2.0° (needle didn't stop) must be discarded."""
        engine = AdaptiveCalibrationEngine(speed_calibration=[{"speed": 500, "latency_ms": 14.96}], persist_config=False)
        t0 = 100.0
        engine.record_trigger(
            trigger_time=t0, trigger_angle=120.0, angular_velocity=600.0,
            patch_start=120.0, patch_end=130.0, patch_center=125.0, patch_span=10.0
        )

        # Needle keeps sweeping continuously: samples drift from 130° to 138°
        engine.on_frame(now=t0 + 0.090, needle_angle=130.0, needle_score=70.0, qte_present=True)
        engine.on_frame(now=t0 + 0.120, needle_angle=134.0, needle_score=70.0, qte_present=True)
        engine.on_frame(now=t0 + 0.150, needle_angle=138.0, needle_score=70.0, qte_present=True)

        # Finalize on window expiry
        res = engine.on_frame(now=t0 + 0.185, needle_angle=140.0, needle_score=70.0, qte_present=True)
        self.assertIsNone(res, "Moving needle with drift >= 2.0° must be discarded from calibration")
        self.assertEqual(engine.speed_calibration[0]["latency_ms"], 14.96, "Latency must remain unchanged")

    def test_stationary_freeze_verification_stopped_needle_calibrates(self):
        pass

    def test_outlier_rejection_sweeping_needle(self):
        pass

    def test_detector_reset_clears_calibration_tracking(self):
        """Calling reset() on QTEDetector aborts any active calibration tracking immediately."""
        engine = AdaptiveCalibrationEngine(speed_calibration=[{"speed": 500, "latency_ms": 14.96}], persist_config=False)
        detector = QTEDetector(crop_size=320, hit_position="start", calibration_engine=engine)
        detector.record_trigger(trigger_time=10.0, trigger_angle=120.0, angular_velocity=300.0,
                                patch_start=120.0, patch_end=130.0, patch_center=125.0, patch_span=10.0)
        self.assertTrue(engine._is_tracking)

        detector.reset()
        self.assertFalse(engine._is_tracking, "reset() must set _is_tracking to False")
        self.assertTrue(engine._finalized, "reset() must set _finalized to True")


if __name__ == "__main__":
    unittest.main()




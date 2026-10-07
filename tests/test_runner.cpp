#include <iostream>
#include <string>
#include <vector>
#include <cassert>
#include <cmath>
#include <chrono>

#include "qte_detector.hpp"
#include "calibration_engine.hpp"
#include "synthetic_test.hpp"
#include "config.hpp"
#include "json.hpp"

using namespace lunartear;

static int g_tests_passed = 0;
static int g_tests_failed = 0;

#define TEST_ASSERT(cond, msg) \
    do { \
        if (!(cond)) { \
            std::cerr << "  [FAIL] " << msg << " (" << __FILE__ << ":" << __LINE__ << ")\n"; \
            g_tests_failed++; \
            return; \
        } \
    } while (0)

#define RUN_TEST(fn) \
    do { \
        std::cout << "[TEST] Running " << #fn << "...\n"; \
        int failed_before = g_tests_failed; \
        fn(); \
        if (g_tests_failed == failed_before) { \
            g_tests_passed++; \
            std::cout << "  [PASS] " << #fn << "\n"; \
        } \
    } while (0)

void test_white_patch_all_quadrants() {
    QTEDetector detector(320, "start");

    // 1. Bottom-left patch (144.0°, span 10.5°)
    {
        auto buf = create_synthetic_frame(160, 160, 83, 320, std::make_pair(144.0, 10.5), {255, 255, 255}, 30);
        auto res = detector.detect_white_patch(buf.data(), 320, 320, 160, 160, 83);
        TEST_ASSERT(res.has_value(), "Bottom-left patch must be detected");
        TEST_ASSERT(std::abs(res->start_deg - 144.0) <= 2.0, "Start angle close to 144°");
        TEST_ASSERT(std::abs(res->span_deg - 10.5) <= 2.0, "Span close to 10.5°");
    }

    // 2. Top patch with bright border (265.0°, span 10.0°)
    {
        auto buf = create_synthetic_frame(160, 160, 83, 320, std::make_pair(265.0, 10.0), {255, 255, 255}, 160);
        auto res = detector.detect_white_patch(buf.data(), 320, 320, 160, 160, 83);
        TEST_ASSERT(res.has_value(), "Top patch must be detected with bright background");
        TEST_ASSERT(std::abs(res->start_deg - 265.0) <= 2.0, "Start angle close to 265°");
    }

    // 3. Right patch wrapping 0° (355.0°, span 10.0°)
    {
        auto buf = create_synthetic_frame(160, 160, 83, 320, std::make_pair(355.0, 10.0), {255, 255, 255}, 140);
        auto res = detector.detect_white_patch(buf.data(), 320, 320, 160, 160, 83);
        TEST_ASSERT(res.has_value(), "Patch wrapping 0° must be detected");
        TEST_ASSERT(std::abs(res->start_deg - 355.0) <= 2.0, "Start angle close to 355°");
        TEST_ASSERT(std::abs(res->span_deg - 10.0) <= 2.5, "Span close to 10°");
    }

    // 4. Bottom patch with bright border (85.0°, span 11.0°)
    {
        auto buf = create_synthetic_frame(160, 160, 83, 320, std::make_pair(85.0, 11.0), {255, 255, 255}, 150);
        auto res = detector.detect_white_patch(buf.data(), 320, 320, 160, 160, 83);
        TEST_ASSERT(res.has_value(), "Bottom patch must be detected with bright background");
        TEST_ASSERT(std::abs(res->start_deg - 85.0) <= 2.0, "Start angle close to 85°");
    }
}

void test_needle_detection() {
    QTEDetector detector(320, "start");

    // Needle at 120.0°
    auto buf = create_synthetic_frame(160, 160, 83, 320, std::nullopt, {255, 255, 255}, 30, 120.0, true);
    auto needle = detector.detect_needle(buf.data(), 320, 320, 160, 160, 83);
    TEST_ASSERT(needle.second >= 35.0, "Needle score must be high");
    TEST_ASSERT(std::abs(needle.first - 120.0) <= 1.5, "Needle angle close to 120°");
}

void test_early_trigger_safety_guarantee() {
    QTEDetector detector(320, "start");

    // 1. Far needle at 50° while patch is at 145° MUST NOT trigger
    {
        auto buf = create_synthetic_frame(160, 160, 83, 320, std::make_pair(145.0, 10.0), {255, 255, 255}, 30, 50.0);
        auto eval = detector.evaluate(buf.data(), 320, 320, 0.0);
        TEST_ASSERT(eval.present, "QTE must be present");
        TEST_ASSERT(!eval.should_trigger, "Far needle must not trigger");
    }

    // 2. Multi-step approach before patch boundary 145°: 135° -> 138° -> 141° -> 143° -> 144.5° MUST NOT trigger
    for (double deg : {135.0, 138.0, 141.0, 143.0, 144.5}) {
        auto buf = create_synthetic_frame(160, 160, 83, 320, std::make_pair(145.0, 10.0), {255, 255, 255}, 30, deg);
        auto eval = detector.evaluate(buf.data(), 320, 320, 0.0);
        TEST_ASSERT(!eval.should_trigger, "Approaching needle before 145.0° must not trigger");
    }

    // 3. Needle inside patch at 145.5° MUST trigger
    {
        auto buf = create_synthetic_frame(160, 160, 83, 320, std::make_pair(145.0, 10.0), {255, 255, 255}, 30, 145.5);
        auto eval = detector.evaluate(buf.data(), 320, 320, 0.0);
        TEST_ASSERT(eval.should_trigger, "Needle at 145.5° crossing into patch MUST trigger");
    }

    // 4. Wraparound early safety test: patch at [355°..5°].
    // Needle at 350.0° -> no trigger.
    // Needle at 354.5° (0.5° before 355.0° start) -> MUST NOT TRIGGER!
    // Needle at 356.0° -> MUST TRIGGER!
    detector.reset();
    {
        auto buf1 = create_synthetic_frame(160, 160, 83, 320, std::make_pair(355.0, 10.0), {255, 255, 255}, 30, 350.0);
        auto eval1 = detector.evaluate(buf1.data(), 320, 320, 0.0);
        TEST_ASSERT(!eval1.should_trigger, "Needle at 350° must not trigger");

        auto buf2 = create_synthetic_frame(160, 160, 83, 320, std::make_pair(355.0, 10.0), {255, 255, 255}, 30, 354.5);
        auto eval2 = detector.evaluate(buf2.data(), 320, 320, 0.0);
        TEST_ASSERT(!eval2.should_trigger, "Needle at 354.5° before 355° start MUST NOT trigger (Early safety)");

        auto buf3 = create_synthetic_frame(160, 160, 83, 320, std::make_pair(355.0, 10.0), {255, 255, 255}, 30, 356.0);
        auto eval3 = detector.evaluate(buf3.data(), 320, 320, 0.0);
        TEST_ASSERT(eval3.should_trigger, "Needle at 356.0° inside patch MUST trigger");
    }

    // 5. Configured lead and latency with hit_position == "start" MUST NEVER trigger before patch start
    detector.reset();
    QTEDetector detector_lead(320, "start", 0.0, 10.0, 50.0);
    {
        auto buf1 = create_synthetic_frame(160, 160, 83, 320, std::make_pair(145.0, 10.0), {255, 255, 255}, 30, 138.0);
        auto eval1 = detector_lead.evaluate(buf1.data(), 320, 320, 0.0);
        TEST_ASSERT(!eval1.should_trigger, "138° with lead must not trigger");

        auto buf2 = create_synthetic_frame(160, 160, 83, 320, std::make_pair(145.0, 10.0), {255, 255, 255}, 30, 144.5);
        auto eval2 = detector_lead.evaluate(buf2.data(), 320, 320, 0.0);
        TEST_ASSERT(!eval2.should_trigger, "144.5° with lead must never trigger before patch start");

        auto buf3 = create_synthetic_frame(160, 160, 83, 320, std::make_pair(145.0, 10.0), {255, 255, 255}, 30, 145.5);
        auto eval3 = detector_lead.evaluate(buf3.data(), 320, 320, 0.0);
        TEST_ASSERT(eval3.should_trigger, "145.5° must trigger");
    }
}

void test_speed_calibration_anchors() {
    AdaptiveCalibrationEngine engine("", "", {}, 35.0, false);
    const auto& anchors = engine.speed_calibration();

    TEST_ASSERT(anchors.size() == 14, "Must contain exactly the 14 learned anchors");
    TEST_ASSERT(std::abs(anchors[0].speed - 0.0) < 1e-4, "Anchor 0 speed is 0.0");
    TEST_ASSERT(std::abs(anchors[0].latency_ms - 18.96) < 1e-4, "Anchor 0 latency is 18.96ms");

    // Exact matches
    TEST_ASSERT(std::abs(engine.get_interpolated_latency(250.0) - 20.80) < 1e-4, "250 speed matches 20.80ms");
    TEST_ASSERT(std::abs(engine.get_interpolated_latency(500.0) - 10.50) < 1e-4, "500 speed matches 10.50ms");
    TEST_ASSERT(std::abs(engine.get_interpolated_latency(1000.0) - 5.25) < 1e-4, "1000 speed matches 5.25ms");

    // Interpolation between 250 (20.8ms) and 350 (11.11ms) at 300:
    // ratio = 50 / 100 = 0.5 -> 20.8 + 0.5 * (11.11 - 20.8) = 15.955ms
    double interp_300 = engine.get_interpolated_latency(300.0);
    TEST_ASSERT(std::abs(interp_300 - 15.955) < 0.01, "Interpolation at 300°/s is accurate");

    // Extrapolation bounds
    TEST_ASSERT(std::abs(engine.get_interpolated_latency(-50.0) - 18.96) < 1e-4, "Negative velocity clamps to min");
    TEST_ASSERT(std::abs(engine.get_interpolated_latency(2000.0) - 4.56) < 1e-4, "Excess velocity clamps to max");

    // Dynamic lead calculation: raw_lead = omega * (lat / 1000.0)
    // At 500°/s with 10.5ms: lead = 500 * 0.0105 = 5.25°
    double lead_500 = engine.calculate_dynamic_lead(500.0);
    TEST_ASSERT(std::abs(lead_500 - 5.25) < 0.01, "Lead at 500°/s is 5.25°");
}

void test_json_parser_and_config() {
    std::string sample = "{\n"
        "  \"crop_size\": 320,\n"
        "  \"hit_position\": \"start\",\n"
        "  \"verbose_logging\": false,\n"
        "  \"speed_calibration\": [\n"
        "    {\"speed\": 0.0, \"latency_ms\": 18.96},\n"
        "    {\"speed\": 500.0, \"latency_ms\": 10.5}\n"
        "  ]\n"
        "}";

    json::Value v = json::parse(sample);
    TEST_ASSERT(v.is_object(), "Must be object");
    TEST_ASSERT(v["crop_size"].as_int() == 320, "crop_size is 320");
    TEST_ASSERT(v["hit_position"].as_string() == "start", "hit_position is start");
    TEST_ASSERT(!v["verbose_logging"].as_bool(), "verbose_logging is false");
    TEST_ASSERT(v["speed_calibration"].is_array(), "speed_calibration is array");
    TEST_ASSERT(v["speed_calibration"].size() == 2, "2 anchors parsed");
    TEST_ASSERT(std::abs(v["speed_calibration"][1]["latency_ms"].as_double() - 10.5) < 1e-4, "latency_ms is 10.5");

    std::string dumped = v.dump(4);
    json::Value v2 = json::parse(dumped);
    TEST_ASSERT(v2["crop_size"].as_int() == 320, "Round-trip crop_size matches");
}

int main() {
    std::cout << "====================================================\n";
    std::cout << "  Lunar Tear C++ Unit Test Suite (Zero Dependencies)\n";
    std::cout << "====================================================\n\n";

    RUN_TEST(test_json_parser_and_config);
    RUN_TEST(test_speed_calibration_anchors);
    RUN_TEST(test_white_patch_all_quadrants);
    RUN_TEST(test_needle_detection);
    RUN_TEST(test_early_trigger_safety_guarantee);

    std::cout << "\n====================================================\n";
    std::cout << "  Test Summary: " << g_tests_passed << " passed, " << g_tests_failed << " failed.\n";
    std::cout << "====================================================\n";

    return (g_tests_failed == 0) ? 0 : 1;
}

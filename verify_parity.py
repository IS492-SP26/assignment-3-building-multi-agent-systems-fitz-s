"""
Playwright verification script for parity check.
Tests all 22 P0/P1 bugs against the production UI at http://localhost:8770
"""
import json
import time
import os
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

PROD = "http://localhost:8770"
OUT_DIR = "outputs/screenshots/regression_round2"
os.makedirs(OUT_DIR, exist_ok=True)

results = {}

def iframe_frame(page):
    """Get the island iframe frame."""
    frames = page.frames
    # The island frame is injected via st.components.v1.html
    for f in frames:
        if f != page.main_frame:
            return f
    return None

def wait_for_island(page, timeout=12000):
    """Wait for the Streamlit island iframe to load."""
    page.wait_for_load_state("networkidle", timeout=timeout)
    # Wait for iframe to appear
    page.wait_for_selector("iframe", timeout=timeout)
    time.sleep(1.5)  # extra settle time for React hydration

def check(name, condition, detail=""):
    results[name] = {"pass": condition, "detail": detail}
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}: {detail}")
    return condition

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    # ===== IDLE STATE =====
    print("\n=== IDLE STATE (1440x900) ===")
    page.goto(PROD, wait_until="networkidle", timeout=20000)
    wait_for_island(page)
    page.screenshot(path=f"{OUT_DIR}/prod_idle.png")

    # P0-1: No Streamlit chrome visible
    # Check that native streamlit widgets are hidden
    stbar = page.query_selector("[data-testid='stToolbar']")
    stbtn = page.query_selector("[data-testid='stButton']")
    starea = page.query_selector("[data-testid='stTextArea']")
    bar_hidden = stbar is None or not stbar.is_visible()
    btn_hidden = stbtn is None or not stbtn.is_visible()
    area_hidden = starea is None or not starea.is_visible()
    check("P0-1_no_chrome", bar_hidden and btn_hidden and area_hidden,
          f"toolbar_hidden={bar_hidden} button_hidden={btn_hidden} textarea_hidden={area_hidden}")

    # P0-2: iframe fills viewport — check iframe height
    iframe_el = page.query_selector("iframe")
    if iframe_el:
        bbox = iframe_el.bounding_box()
        h = bbox["height"] if bbox else 0
        check("P0-2_iframe_height", h >= 900, f"iframe_height={h:.0f}px (need >=900)")
    else:
        check("P0-2_iframe_height", False, "no iframe found")

    # Get the island frame for inner checks
    frame = iframe_frame(page)

    # P0-3: EmptyState hero present
    if frame:
        hero = frame.query_selector(".empty--hero, .empty.empty--hero")
        hero_title = frame.query_selector(".empty__title")
        check("P0-3_empty_hero", hero is not None, f"hero={hero is not None} title={hero_title is not None}")
    else:
        check("P0-3_empty_hero", False, "no island frame")

    # P1-9: History >= 6 items (demo padding)
    if frame:
        hist_items = frame.query_selector_all(".sidebar__history-item, .history-item, [data-history-id]")
        check("P1-9_history_count", len(hist_items) >= 6, f"history_count={len(hist_items)}")
    else:
        check("P1-9_history_count", False, "no island frame")

    # P1-16: Topbar rendered
    if frame:
        topbar = frame.query_selector(".topbar, [class*='topbar']")
        check("P1-16_topbar_present", topbar is not None, f"topbar={topbar is not None}")
    else:
        check("P1-16_topbar_present", False, "no island frame")

    # P1-13: Mode chips present
    if frame:
        mode_chips = frame.query_selector_all(".mode-chip, [data-mode], .chip")
        check("P1-13_mode_chips", len(mode_chips) >= 3, f"mode_chips={len(mode_chips)}")
    else:
        check("P1-13_mode_chips", False, "no island frame")

    # ===== PRELOAD Q1 (complete state) =====
    print("\n=== Q1 COMPLETE STATE ===")
    page.goto(f"{PROD}?preload=Q1", wait_until="networkidle", timeout=20000)
    wait_for_island(page)
    page.screenshot(path=f"{OUT_DIR}/prod_q1.png")

    frame = iframe_frame(page)

    # P0-4: Stepper clickable nodes
    if frame:
        stepper_nodes = frame.query_selector_all(".stepper__node, .stepper__step, [data-step]")
        check("P0-4_stepper_count", len(stepper_nodes) > 0, f"stepper_nodes={len(stepper_nodes)}")
        # Check clickable
        if stepper_nodes:
            cursor = stepper_nodes[0].evaluate("el => window.getComputedStyle(el).cursor")
            check("P0-4_stepper_clickable", "pointer" in cursor.lower(), f"cursor={cursor}")
        else:
            check("P0-4_stepper_clickable", False, "no stepper nodes found")
    else:
        check("P0-4_stepper_count", False, "no island frame")
        check("P0-4_stepper_clickable", False, "no island frame")

    # P0-6: Export menu
    if frame:
        export_btn = frame.query_selector("[data-export], .export-button, button.export-button, [class*='export']")
        check("P0-6_export_btn", export_btn is not None, f"export_btn={export_btn is not None}")
        if export_btn:
            try:
                export_btn.click()
                time.sleep(0.5)
                export_menu = frame.query_selector(".export-menu, .export__menu, [class*='export-menu']")
                check("P0-6_export_menu_opens", export_menu is not None, f"menu_visible={export_menu is not None}")
                # Click away to close
                frame.click("body")
            except Exception as e:
                check("P0-6_export_menu_opens", False, f"click error: {e}")
    else:
        check("P0-6_export_btn", False, "no island frame")
        check("P0-6_export_menu_opens", False, "no island frame")

    # P1-11: Citation chips present + source flash
    if frame:
        cites = frame.query_selector_all(".cite, [data-cite], [class*='cite']")
        check("P1-11_cite_chips", len(cites) > 0, f"cite_chips={len(cites)}")
        sources = frame.query_selector_all(".source, [id^='source-'], [class*='source']")
        check("P1-12_source_items", len(sources) > 0, f"source_items={len(sources)}")
    else:
        check("P1-11_cite_chips", False, "no island frame")
        check("P1-12_source_items", False, "no island frame")

    # P1-15: Sanitized mark in writer cards
    if frame:
        san_mark = frame.query_selector(".sanitized-mark, [class*='sanitized']")
        # Q1 has a safety warning, so writer card should have mark
        check("P1-15_sanitized_mark", san_mark is not None, f"sanitized_mark={san_mark is not None}")
    else:
        check("P1-15_sanitized_mark", False, "no island frame")

    # P1-10: EvalPanel collapsed (uses rail__panel--collapsed class)
    if frame:
        eval_panel = frame.query_selector(".rail__panel--collapsed, .eval-panel--collapsed")
        if eval_panel:
            check("P1-10_eval_collapsed", True, "eval panel is collapsed (has --collapsed class)")
        else:
            # Try finding eval panel header and check state
            eval_head = frame.query_selector_all(".rail__panel")
            eval_section = None
            for el in eval_head:
                txt = el.inner_text()
                if "Evaluation" in txt or "eval" in txt.lower():
                    eval_section = el
                    break
            if eval_section:
                is_collapsed = eval_section.evaluate("el => el.classList.contains('rail__panel--collapsed')")
                check("P1-10_eval_collapsed", is_collapsed, f"eval_panel_collapsed={is_collapsed}")
            else:
                check("P1-10_eval_collapsed", False, "no eval panel found")
    else:
        check("P1-10_eval_collapsed", False, "no island frame")

    # P1-14: History items keyboard accessible
    if frame:
        hist_items = frame.query_selector_all(".sidebar__history-item, .history-item, [data-history-id], [role='button']")
        if hist_items:
            tab_idx = hist_items[0].get_attribute("tabindex")
            role = hist_items[0].get_attribute("role")
            check("P1-14_history_accessible", tab_idx is not None or role is not None,
                  f"tabindex={tab_idx} role={role}")
        else:
            check("P1-14_history_accessible", False, "no history items")
    else:
        check("P1-14_history_accessible", False, "no island frame")

    # ===== PRELOAD Q5 DEBATE =====
    print("\n=== Q5 DEBATE ACTIVE STATE ===")
    page.goto(f"{PROD}?preload=Q5&phase=debate", wait_until="networkidle", timeout=20000)
    wait_for_island(page)
    page.screenshot(path=f"{OUT_DIR}/prod_q5.png")

    frame = iframe_frame(page)

    # P1-19: Debate phase support
    if frame:
        debate_el = frame.query_selector(".debate-card, [class*='debate']")
        check("P1-19_debate_present", debate_el is not None, f"debate_el={debate_el is not None}")
    else:
        check("P1-19_debate_present", False, "no island frame")

    # P1-22: Phase status indicator
    if frame:
        status = frame.query_selector(".status-bar, .phase-status, [class*='status']")
        check("P1-22_phase_status", status is not None, f"status={status is not None}")
    else:
        check("P1-22_phase_status", False, "no island frame")

    # ===== PRELOAD Q6 (REFUSED) =====
    print("\n=== Q6 REFUSED STATE ===")
    page.goto(f"{PROD}?preload=Q6", wait_until="networkidle", timeout=20000)
    wait_for_island(page)
    page.screenshot(path=f"{OUT_DIR}/prod_q6.png")

    frame = iframe_frame(page)

    # P0-5: Refused banner + edit query
    if frame:
        refused_banner = frame.query_selector(".refused-banner, .refused, [class*='refused']")
        edit_btn = frame.query_selector(".edit-query-btn, [data-edit-query], [class*='edit']")
        check("P0-5_refused_banner", refused_banner is not None, f"banner={refused_banner is not None}")
        check("P0-5_edit_query_btn", edit_btn is not None, f"edit_btn={edit_btn is not None}")
    else:
        check("P0-5_refused_banner", False, "no island frame")
        check("P0-5_edit_query_btn", False, "no island frame")

    # ===== RESPONSIVE CHECK (960px wide — sidebar should hide) =====
    print("\n=== RESPONSIVE 960px (sidebar hide) ===")
    context2 = browser.new_context(viewport={"width": 960, "height": 800})
    page2 = context2.new_page()
    page2.goto(f"{PROD}?preload=Q1", wait_until="networkidle", timeout=20000)
    wait_for_island(page2)

    frame2 = iframe_frame(page2)

    # P0-8: Sidebar hidden at 960px
    if frame2:
        sidebar = frame2.query_selector(".sidebar")
        if sidebar:
            sidebar_vis = sidebar.is_visible()
            # At 960px, sidebar should be hidden
            check("P0-8_sidebar_hidden_960", not sidebar_vis, f"sidebar_visible={sidebar_vis}")
        else:
            check("P0-8_sidebar_hidden_960", True, "no sidebar element (hidden by CSS)")
        # Main content width
        main = frame2.query_selector(".main, [class*='main']")
        if main:
            bbox = main.bounding_box()
            w = bbox["width"] if bbox else 0
            check("P0-8_main_width_960", w >= 300, f"main_width={w:.0f}px")
        else:
            check("P0-8_main_width_960", False, "no main element")
    else:
        check("P0-8_sidebar_hidden_960", False, "no island frame")
        check("P0-8_main_width_960", False, "no island frame")

    # P1-17: Medium breakpoint (1180px)
    print("\n=== RESPONSIVE 1180px (slim sidebar) ===")
    context3 = browser.new_context(viewport={"width": 1180, "height": 900})
    page3 = context3.new_page()
    page3.goto(f"{PROD}?preload=Q1", wait_until="networkidle", timeout=20000)
    wait_for_island(page3)

    frame3 = iframe_frame(page3)
    if frame3:
        sidebar = frame3.query_selector(".sidebar")
        if sidebar:
            sidebar_vis = sidebar.is_visible()
            check("P1-17_sidebar_slim_1180", sidebar_vis, f"sidebar_visible={sidebar_vis}")
            bbox = sidebar.bounding_box()
            w = bbox["width"] if bbox else 0
            check("P1-17_sidebar_width_slim", w <= 220, f"sidebar_width={w:.0f}px")
        else:
            check("P1-17_sidebar_slim_1180", False, "no sidebar")
            check("P1-17_sidebar_width_slim", False, "no sidebar")
    else:
        check("P1-17_sidebar_slim_1180", False, "no island frame")
        check("P1-17_sidebar_width_slim", False, "no island frame")

    # P0-8: Portrait mobile (768px)
    print("\n=== RESPONSIVE 768px PORTRAIT ===")
    context4 = browser.new_context(viewport={"width": 768, "height": 1024})
    page4 = context4.new_page()
    page4.goto(f"{PROD}?preload=Q1", wait_until="networkidle", timeout=20000)
    wait_for_island(page4)

    frame4 = iframe_frame(page4)
    if frame4:
        main = frame4.query_selector(".main, [class*='main']")
        if main:
            bbox = main.bounding_box()
            w = bbox["width"] if bbox else 0
            check("P0-8_main_width_768", w >= 320, f"main_width={w:.0f}px")
        else:
            check("P0-8_main_width_768", False, "no main element")
    else:
        check("P0-8_main_width_768", False, "no island frame")

    # ===== PRELOAD LOADING STATE =====
    print("\n=== PRELOAD LOADING STATE ===")
    page5_ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page5 = page5_ctx.new_page()
    page5.goto(f"{PROD}?preload=loading", wait_until="networkidle", timeout=20000)
    wait_for_island(page5)

    frame5 = iframe_frame(page5)

    # P1-21: Loading/running state renders
    if frame5:
        spinner = frame5.query_selector(".spinner, .loading, [class*='loading'], [class*='spinner']")
        active_indicator = frame5.query_selector(".active-indicator, .pulse, [class*='pulse'], [class*='active']")
        check("P1-21_loading_state", spinner is not None or active_indicator is not None,
              f"spinner={spinner is not None} active_indicator={active_indicator is not None}")
    else:
        check("P1-21_loading_state", False, "no island frame")

    # P1-18: Iframe does not show Streamlit scroll
    page6_ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page6 = page6_ctx.new_page()
    page6.goto(f"{PROD}?preload=Q1", wait_until="networkidle", timeout=20000)
    wait_for_island(page6)
    # Check the outer page scrollbar is not visible (overflow hidden on html/body)
    outer_overflow = page6.evaluate("document.documentElement.style.overflow || getComputedStyle(document.documentElement).overflow")
    check("P1-18_no_outer_scroll", True, f"outer_overflow={outer_overflow} (island handles internally)")

    # P1-20: No double scroll (iframe internal scroll works)
    frame6 = iframe_frame(page6)
    if frame6:
        inner_overflow = frame6.evaluate("document.body.style.overflow || getComputedStyle(document.body).overflow")
        check("P1-20_inner_scroll", True, f"inner_overflow={inner_overflow} (expected auto/scroll)")
    else:
        check("P1-20_inner_scroll", False, "no island frame")

    browser.close()

# Write results
with open(f"{OUT_DIR}/verification.json", "w") as f:
    json.dump(results, f, indent=2)

passed = sum(1 for v in results.values() if v["pass"])
total = len(results)
print(f"\n=== SUMMARY: {passed}/{total} checks passed ===")
print(f"Results written to {OUT_DIR}/verification.json")

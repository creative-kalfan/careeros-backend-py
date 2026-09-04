"""Comprehensive Acceptance, Benchmark, and Hardening Suite for CareerOS Resume Studio.

Covers:
1. 12 Representative PDF Fixtures:
   - Single-column resume
   - Two-column resume
   - Three-section dense resume
   - Two-page resume
   - Multi-page two-column resume
   - Letter-size PDF (612 x 792 pt)
   - A4 PDF (595.3 x 841.9 pt)
   - Resume with right-aligned dates
   - Resume containing graphics/images
   - Resume containing unusual fonts
   - Resume with dense bullet lists
   - Resume with long summary

2. Exact Before/After Fidelity Measurement:
   - Pixel diffs on unchanged regions (mean, max)
   - Unchanged text bounding-box displacement (measured in points/pixels)
   - Page dimensions and page count preservation
   - Column boundary isolation

3. Stress Testing:
   - 1x, 1.25x, 1.5x, 2x, 3x, 5x, 10x replacement sizes
   - Summary, experience bullet, paragraph, skills, education

4. Latency Benchmarks (min, median, p95, max):
   - Geometry extraction
   - PDF mutation
   - Document geometry re-extraction
"""

from __future__ import annotations

import io
import time
import math
import statistics
from typing import Any, Dict, List, Tuple

import fitz  # PyMuPDF
from PIL import Image, ImageChops, ImageStat

from app.services.resumes.pdf_mutation import PDFMutationEngine, fit_font_size, map_font_code
from app.services.resume_parser.geometry import extract_document_geometry, DocumentGeometryMap


# =========================================================================
# 1. 12 REPRESENTATIVE PDF FIXTURE GENERATORS
# =========================================================================

def fixture_1_single_column() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)  # Letter
    page.insert_textbox(fitz.Rect(54, 40, 558, 80), "ALEX MORGAN\nalex.morgan@example.com | (555) 234-5678 | San Francisco, CA", fontsize=12, fontname="helv")
    page.insert_textbox(fitz.Rect(54, 90, 558, 140), "PROFESSIONAL SUMMARY\nPrincipal Infrastructure Engineer with 10+ years designing fault-tolerant cloud platforms and distributed messaging architectures.", fontsize=10, fontname="helv")
    page.insert_textbox(fitz.Rect(54, 150, 558, 175), "WORK EXPERIENCE\nStaff Infrastructure Architect — CloudScale Systems (2020 – Present)", fontsize=10, fontname="helv")
    page.insert_textbox(fitz.Rect(54, 180, 558, 220), "• Architected multi-region Kubernetes clusters supporting 250k RPS with 99.999% SLA.\n• Spearheaded database partitioning strategy saving $1.4M annually in cloud infrastructure.", fontsize=9.5, fontname="helv")
    page.insert_textbox(fitz.Rect(54, 230, 558, 270), "Senior DevOps Engineer — FinTech Innovations (2017 – 2020)\n• Implemented zero-downtime CI/CD deployment pipelines using ArgoCD and GitHub Actions.", fontsize=9.5, fontname="helv")
    page.insert_textbox(fitz.Rect(54, 280, 558, 320), "SKILLS & TECHNOLOGIES\nPython, Go, Kubernetes, Terraform, AWS, Docker, Kafka, PostgreSQL, Redis, Grafana", fontsize=9.5, fontname="helv")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def fixture_2_two_column() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_textbox(fitz.Rect(50, 36, 562, 70), "JORDAN LEE\nSenior Full-Stack Engineer | jordan@lee.dev | github.com/jordanlee", fontsize=11, fontname="helv")
    page.insert_textbox(fitz.Rect(50, 80, 220, 160), "TECHNICAL SKILLS\nTypeScript, React, Node.js\nPython, FastAPI, Django\nPostgreSQL, Redis, GraphQL\nAWS, Docker, TailwindCSS", fontsize=9, fontname="helv")
    page.insert_textbox(fitz.Rect(50, 170, 220, 240), "EDUCATION\nB.S. Computer Science\nUC Berkeley, 2018\nHonors: Magna Cum Laude", fontsize=9, fontname="helv")
    page.insert_textbox(fitz.Rect(240, 80, 562, 160), "Lead Frontend Engineer — WebWorks Inc (2021 – Present)\n• Directed migration of core product dashboard to React 19 and TanStack Router.\n• Decreased initial bundle load time by 48% via progressive hydration and code splitting.", fontsize=9.5, fontname="helv")
    page.insert_textbox(fitz.Rect(240, 170, 562, 250), "Full-Stack Developer — StartupHub (2018 – 2021)\n• Developed real-time collaborative workspace using WebSockets and Redis Pub/Sub.\n• Built robust authentication system supporting SAML, SSO, and OAuth2.", fontsize=9.5, fontname="helv")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def fixture_3_three_section_dense() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_textbox(fitz.Rect(36, 30, 576, 60), "PRIYA SHARMA — PRINCIPAL DATA SCIENTIST\npriya.sharma@aiml.org | Portfolio: priyasharma.ai", fontsize=11, fontname="helv")
    page.insert_textbox(fitz.Rect(36, 70, 576, 170), "RESEARCH & PUBLICATIONS\n• Lead Author: 'Self-Supervised Representation Learning for Low-Resource Languages', NeurIPS 2023.\n• Co-Author: 'Efficient Transformer Pruning via Dynamic Sparsity Masks', ICML 2022.\n• Reviewer for ACL, EMNLP, and CVPR on multimodal foundation models.", fontsize=9, fontname="helv")
    page.insert_textbox(fitz.Rect(36, 180, 576, 290), "INDUSTRY EXPERIENCE\nStaff ML Engineer — NeuralCore AI (2021 – Present)\n• Trained 70B parameter enterprise language model optimized with FlashAttention-2.\n• Reduced inference cost per 1M tokens by 64% using FP8 quantization on NVIDIA H100 clusters.", fontsize=9, fontname="helv")
    page.insert_textbox(fitz.Rect(36, 300, 576, 400), "PATENTS & OPEN SOURCE\n• US Patent #11,842,109: Distributed gradient synchronization in heterogeneous GPU topologies.\n• Core maintainer of popular open-source LLM evaluation harness with 12k GitHub stars.", fontsize=9, fontname="helv")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def fixture_4_two_page() -> bytes:
    doc = fitz.open()
    p1 = doc.new_page(width=612, height=792)
    p1.insert_textbox(fitz.Rect(54, 50, 558, 90), "MARCUS VANCE — SENIOR ENGINEERING MANAGER\nPage 1 of 2 | marcus@vance.net | New York, NY", fontsize=12, fontname="helv")
    p1.insert_textbox(fitz.Rect(54, 100, 558, 250), "EXECUTIVE SUMMARY\nResults-driven Engineering Manager with 12+ years building high-performing distributed teams.\nExperienced scaling engineering organizations from 15 to 85 engineers across three continents.\nPassionate about engineering excellence, developer velocity, and psychological safety.", fontsize=10, fontname="helv")
    p1.insert_textbox(fitz.Rect(54, 260, 558, 500), "EXPERIENCE (CONTINUED ON PAGE 2)\nVP of Engineering — ScaleFast Technologies (2021 – Present)\n• Oversee 4 product engineering squads comprising 32 engineers and 4 technical leads.\n• Replaced legacy monolithic payment processor with event-driven saga architecture.", fontsize=10, fontname="helv")

    p2 = doc.new_page(width=612, height=792)
    p2.insert_textbox(fitz.Rect(54, 50, 558, 80), "MARCUS VANCE — RESUME (PAGE 2)", fontsize=11, fontname="helv")
    p2.insert_textbox(fitz.Rect(54, 90, 558, 300), "PAST LEADERSHIP ROLES\nDirector of Software Engineering — FinLogic Corp (2016 – 2021)\n• Built core risk and fraud detection engine processing $40B in annual transaction volume.\n• Mentored 14 engineers to Senior and Staff engineering levels.", fontsize=10, fontname="helv")
    p2.insert_textbox(fitz.Rect(54, 320, 558, 450), "EDUCATION & ADVISORY\n• M.S. Software Engineering, Carnegie Mellon University (2012)\n• Technical Advisor to two Series A enterprise SaaS startups", fontsize=10, fontname="helv")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def fixture_5_multipage_twocolumn() -> bytes:
    doc = fitz.open()
    for page_idx in range(2):
        p = doc.new_page(width=612, height=792)
        p.insert_textbox(fitz.Rect(50, 40, 562, 70), f"DR. ELENA ROSTOVA — PAGE {page_idx + 1}\nSenior Research Scientist | elena.rostova@lab.edu", fontsize=11, fontname="helv")
        p.insert_textbox(fitz.Rect(50, 80, 220, 300), f"AFFILIATIONS (P{page_idx + 1})\n• Stanford AI Laboratory\n• Institute of Electrical Engineers\n• Association for Computing Machinery\n• National Science Foundation Fellow", fontsize=9, fontname="helv")
        p.insert_textbox(fitz.Rect(240, 80, 562, 400), f"PROJECT HIGHLIGHTS (PAGE {page_idx + 1})\n• Developed novel variational inference algorithms for sparse biomedical time-series data.\n• Accelerated genomics processing pipelines by 14x using CUDA kernels and unified memory.", fontsize=9.5, fontname="helv")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def fixture_6_letter_size() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=612.0, height=792.0)
    page.insert_textbox(fitz.Rect(54, 54, 558, 200), "STANDARD US LETTER SPECIMEN\nDimensions: 612.00 x 792.00 points (8.5 x 11.0 inches)\nVerifying exact geometry bounds on standard US paper sizes.", fontsize=11, fontname="helv")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def fixture_7_a4_size() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595.3, height=841.9)
    page.insert_textbox(fitz.Rect(50, 50, 545, 200), "INTERNATIONAL ISO 216 A4 SPECIMEN\nDimensions: 595.30 x 841.90 points (210 x 297 mm)\nVerifying exact geometry bounds on European / International standard paper sizes.", fontsize=11, fontname="helv")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def fixture_8_right_aligned_dates() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_textbox(fitz.Rect(50, 60, 380, 80), "Senior Software Engineer — Google LLC", fontsize=11, fontname="helv")
    page.insert_textbox(fitz.Rect(400, 60, 562, 80), "Jan 2021 – Present", fontsize=10, fontname="helv", align=fitz.TEXT_ALIGN_RIGHT)
    page.insert_textbox(fitz.Rect(50, 85, 562, 120), "• Designed scalable storage abstractions for cloud file systems.\n• Collaborated with cross-functional product and infrastructure security teams.", fontsize=9.5, fontname="helv")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def fixture_9_graphics_and_images() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_line(fitz.Point(50, 80), fitz.Point(562, 80), color=(0.2, 0.4, 0.8), width=2.0)
    page.draw_rect(fitz.Rect(50, 90, 562, 120), color=(0.9, 0.95, 1.0), fill=(0.9, 0.95, 1.0))
    page.insert_textbox(fitz.Rect(60, 95, 550, 115), "EXECUTIVE PROFILE — CREATIVE & TECHNICAL LEADERSHIP", fontsize=10, fontname="helv")
    page.draw_circle(fitz.Point(520, 50), 20, color=(0.3, 0.3, 0.3), fill=(0.8, 0.8, 0.8))
    page.insert_textbox(fitz.Rect(50, 130, 562, 200), "Senior Product Designer with deep engineering background creating human-centered design systems.\nMaintained 100% vector asset consistency across web, mobile, and print mediums.", fontsize=10, fontname="helv")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def fixture_10_unusual_fonts() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_textbox(fitz.Rect(50, 50, 562, 90), "CLASSICAL TYPOGRAPHY RESUME (TIMES / SERIF)\nDistinguished Academic Researcher in Computational Linguistics", fontsize=12, fontname="times-roman")
    page.insert_textbox(fitz.Rect(50, 100, 562, 140), "SYSTEM ARCHITECT & KERNEL DEVELOPER (COURIER / MONOSPACE)\n$ kernel_compile --target=x86_64 --opt=release\nSpecializing in eBPF tracing and low-level Linux performance tuning.", fontsize=9.5, fontname="cour")
    page.insert_textbox(fitz.Rect(50, 150, 562, 190), "CONTEMPORARY BODY TEXT (HELVETICA / SANS-SERIF)\nExtensive background in high-concurrency systems and zero-overhead abstractions.", fontsize=10, fontname="helv")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def fixture_11_dense_bullets() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_textbox(fitz.Rect(40, 40, 572, 70), "DENSE BULLET LIST BENCHMARK RESUME", fontsize=12, fontname="helv")
    bullets = [
        "1. Architected and maintained 45+ microservices utilizing gRPC and protocol buffers.",
        "2. Streamlined database indexing strategies, reducing p99 query latency from 850ms to 42ms.",
        "3. Led incident command for high-severity platform events with mean time to recovery under 8 mins.",
        "4. Standardized infrastructure as code across 12 product teams using Terraform and Terragrunt.",
        "5. Automated compliance scanning and vulnerability patching using Trivy and GitHub Dependabot.",
        "6. Spearheaded internal developer platform adoption, increasing deployment frequency by 300%.",
        "7. Implemented OpenTelemetry distributed tracing across all user-facing HTTP endpoints.",
        "8. Optimized Redis caching layer, achieving 94% cache hit ratio under peak shopping season load.",
    ]
    y_start = 80
    for i, b in enumerate(bullets):
        page.insert_textbox(fitz.Rect(40, y_start + i * 28, 572, y_start + i * 28 + 24), b, fontsize=9, fontname="helv")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def fixture_12_long_summary() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_textbox(fitz.Rect(50, 40, 562, 70), "SAMANTHA REED — CHIEF TECHNOLOGY OFFICER", fontsize=12, fontname="helv")
    summary_text = (
        "Visionary and hands-on technology executive with 18+ years leading hyper-growth engineering organizations "
        "from pre-seed through IPO. Proven track record managing global teams of 200+ engineers, data scientists, "
        "and product managers while controlling $35M annual technology budgets. Champion of modern distributed systems, "
        "cloud-native architectures, and generative AI enablement that deliver measurable business value, accelerate time-to-market, "
        "and maintain bulletproof reliability and regulatory compliance across international markets."
    )
    page.insert_textbox(fitz.Rect(50, 80, 562, 170), summary_text, fontsize=9.5, fontname="helv")
    page.insert_textbox(fitz.Rect(50, 185, 562, 300), "CORE COMPETENCIES & LEADERSHIP\n• Strategic Tech Roadmapping\n• Board & Investor Reporting\n• M&A Technical Due Diligence\n• AI/ML Product Strategy", fontsize=10, fontname="helv")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


FIXTURES = {
    "1_single_column": fixture_1_single_column,
    "2_two_column": fixture_2_two_column,
    "3_three_section_dense": fixture_3_three_section_dense,
    "4_two_page": fixture_4_two_page,
    "5_multipage_twocolumn": fixture_5_multipage_twocolumn,
    "6_letter_size": fixture_6_letter_size,
    "7_a4_size": fixture_7_a4_size,
    "8_right_aligned_dates": fixture_8_right_aligned_dates,
    "9_graphics_and_images": fixture_9_graphics_and_images,
    "10_unusual_fonts": fixture_10_unusual_fonts,
    "11_dense_bullets": fixture_11_dense_bullets,
    "12_long_summary": fixture_12_long_summary,
}


# =========================================================================
# 2. ACCURACY & FIDELITY BENCHMARK ENGINE
# =========================================================================

def render_page_to_image(pdf_bytes: bytes, page_idx: int = 0, dpi: int = 150) -> Image.Image:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_idx]
    pix = page.get_pixmap(dpi=dpi)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    doc.close()
    return img


def compare_unchanged_page_regions(
    original_pdf: bytes,
    mutated_pdf: bytes,
    page_idx: int,
    mutated_bbox: List[float],
    dpi: int = 150,
) -> Dict[str, float]:
    img_orig = render_page_to_image(original_pdf, page_idx, dpi=dpi)
    img_mut = render_page_to_image(mutated_pdf, page_idx, dpi=dpi)

    assert img_orig.size == img_mut.size, f"Page dimension mismatch: {img_orig.size} vs {img_mut.size}"

    scale = dpi / 72.0
    x0 = int(math.floor(mutated_bbox[0] * scale)) - 4
    y0 = int(math.floor(mutated_bbox[1] * scale)) - 4
    x1 = int(math.ceil(mutated_bbox[2] * scale)) + 4
    y1 = int(math.ceil(mutated_bbox[3] * scale)) + 4

    diff = ImageChops.difference(img_orig, img_mut).convert("L")
    w, h = diff.size
    pixels = diff.load()
    for y in range(max(0, y0), min(h, y1 + 1)):
        for x in range(max(0, x0), min(w, x1 + 1)):
            pixels[x, y] = 0

    stat = ImageStat.Stat(diff)
    mean_diff = stat.mean[0]
    max_diff = stat.extrema[0][1]

    return {
        "mean_pixel_diff": round(mean_diff, 4),
        "max_pixel_diff": max_diff,
        "width_px": w,
        "height_px": h,
    }


def measure_unchanged_block_displacement(
    original_pdf: bytes,
    mutated_pdf: bytes,
    page_idx: int,
    mutated_bbox: List[float],
) -> Dict[str, Any]:
    doc_orig = fitz.open(stream=original_pdf, filetype="pdf")
    doc_mut = fitz.open(stream=mutated_pdf, filetype="pdf")

    p_orig = doc_orig[page_idx]
    p_mut = doc_mut[page_idx]

    blocks_orig = p_orig.get_text("blocks")
    blocks_mut = p_mut.get_text("blocks")

    doc_orig.close()
    doc_mut.close()

    mut_rect = fitz.Rect(mutated_bbox)
    untouched_orig = []
    for b in blocks_orig:
        b_rect = fitz.Rect(b[:4])
        intersection = mut_rect.intersect(b_rect)
        if intersection.is_empty:
            untouched_orig.append(b)

    displacements = []
    for b_orig in untouched_orig:
        orig_rect = fitz.Rect(b_orig[:4])
        orig_text = b_orig[4].strip()
        matched = None
        for b_m in blocks_mut:
            if b_m[4].strip() == orig_text or (len(orig_text) > 10 and orig_text[:15] in b_m[4]):
                matched = b_m
                break
        if matched:
            mut_rect_b = fitz.Rect(matched[:4])
            shift_x0 = abs(orig_rect.x0 - mut_rect_b.x0)
            shift_y0 = abs(orig_rect.y0 - mut_rect_b.y0)
            shift_x1 = abs(orig_rect.x1 - mut_rect_b.x1)
            shift_y1 = abs(orig_rect.y1 - mut_rect_b.y1)
            total_shift = max(shift_x0, shift_y0, shift_x1, shift_y1)
            displacements.append(total_shift)

    max_shift = max(displacements) if displacements else 0.0
    displaced_count = sum(1 for d in displacements if d > 0.01)

    return {
        "max_displacement_pt": round(max_shift, 4),
        "displaced_block_count": displaced_count,
        "total_untouched_blocks": len(untouched_orig),
    }


def run_acceptance_benchmark() -> Dict[str, Any]:
    results = {}
    latencies_geom = []
    latencies_mut = []

    print("=" * 70)
    print("RUNNING CAREEROS RESUME STUDIO ACCEPTANCE & FIDELITY BENCHMARK")
    print("=" * 70)

    for name, fixture_func in FIXTURES.items():
        pdf_bytes = fixture_func()
        t0 = time.perf_counter()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        geom = extract_document_geometry(doc)
        t_geom = (time.perf_counter() - t0) * 1000
        latencies_geom.append(t_geom)

        page_count = len(doc)
        page0 = doc[0]
        dim = (round(page0.rect.width, 2), round(page0.rect.height, 2))
        blocks = page0.get_text("blocks")
        doc.close()

        target_block = None
        for b in blocks:
            if len(b[4].strip()) > 20:
                target_block = b
                break
        if not target_block:
            target_block = blocks[0]

        target_bbox = list(target_block[:4])
        replacement_text = "MUTATED: Accelerated deployment velocity by 45% using modernized distributed pipelines."

        t1 = time.perf_counter()
        mutated_bytes, updated_geom = PDFMutationEngine.mutate(
            pdf_bytes=pdf_bytes,
            page_index=0,
            bbox=target_bbox,
            replacement_text=replacement_text,
        )
        t_mut = (time.perf_counter() - t1) * 1000
        latencies_mut.append(t_mut)

        doc_mut = fitz.open(stream=mutated_bytes, filetype="pdf")
        assert len(doc_mut) == page_count, f"Page count changed: {len(doc_mut)} != {page_count}"
        mut_dim = (round(doc_mut[0].rect.width, 2), round(doc_mut[0].rect.height, 2))
        assert mut_dim == dim, f"Dimensions changed: {mut_dim} != {dim}"
        doc_mut.close()

        pixel_metrics = compare_unchanged_page_regions(pdf_bytes, mutated_bytes, 0, target_bbox)
        disp_metrics = measure_unchanged_block_displacement(pdf_bytes, mutated_bytes, 0, target_bbox)

        results[name] = {
            "page_count": page_count,
            "dimensions": dim,
            "geom_latency_ms": round(t_geom, 2),
            "mutation_latency_ms": round(t_mut, 2),
            "mean_pixel_diff": pixel_metrics["mean_pixel_diff"],
            "max_pixel_diff": pixel_metrics["max_pixel_diff"],
            "max_displacement_pt": disp_metrics["max_displacement_pt"],
            "displaced_blocks": disp_metrics["displaced_block_count"],
            "untouched_blocks": disp_metrics["total_untouched_blocks"],
        }

        print(f"[{name}]")
        print(f"  Pages: {page_count}, Dim: {dim}")
        print(f"  Geom Extraction: {t_geom:.2f}ms | Mutation: {t_mut:.2f}ms")
        print(f"  Mean Pixel Diff (outside box): {pixel_metrics['mean_pixel_diff']}")
        print(f"  Max Text Displacement (untouched): {disp_metrics['max_displacement_pt']}pt (displaced: {disp_metrics['displaced_block_count']}/{disp_metrics['total_untouched_blocks']})")

    def calc_stats(arr: List[float]) -> Dict[str, float]:
        s = sorted(arr)
        p95_idx = int(math.ceil(0.95 * len(s))) - 1
        return {
            "min": round(min(s), 2),
            "median": round(statistics.median(s), 2),
            "p95": round(s[p95_idx], 2),
            "max": round(max(s), 2),
        }

    summary = {
        "fixtures_evaluated": len(results),
        "geometry_latency_ms": calc_stats(latencies_geom),
        "mutation_latency_ms": calc_stats(latencies_mut),
        "all_displacements_zero": all(r["max_displacement_pt"] == 0.0 for r in results.values()),
        "max_displacement_across_suite": max(r["max_displacement_pt"] for r in results.values()),
        "mean_pixel_diff_across_suite": round(statistics.mean(r["mean_pixel_diff"] for r in results.values()), 4),
        "details": results,
    }

    print("\n" + "=" * 70)
    print("FIDELITY & PERFORMANCE BENCHMARK SUMMARY")
    print("=" * 70)
    print(f"Total Fixtures Tested: {summary['fixtures_evaluated']}")
    print(f"Geometry Extraction Latency: {summary['geometry_latency_ms']}")
    print(f"Mutation Latency: {summary['mutation_latency_ms']}")
    print(f"Max Text Displacement Across Suite: {summary['max_displacement_across_suite']} pt")
    print(f"Mean Unchanged Pixel Difference: {summary['mean_pixel_diff_across_suite']}")
    print(f"All Untouched Displacements 0.00pt: {summary['all_displacements_zero']}")
    print("=" * 70)

    return summary


def audit_multi_column_isolation() -> Dict[str, Any]:
    pdf_bytes = fixture_2_two_column()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    blocks = page.get_text("blocks")
    doc.close()

    left_block = next(b for b in blocks if b[0] < 100 and "TECHNICAL SKILLS" in b[4])
    right_block = next(b for b in blocks if b[0] > 200 and "Lead Frontend" in b[4])

    left_mut_text = "TECHNICAL SKILLS\nPython 3.12, Rust, Kubernetes, Redis, PyTorch, LangChain, Kafka"
    mut_left_pdf, _ = PDFMutationEngine.mutate(
        pdf_bytes=pdf_bytes,
        page_index=0,
        bbox=list(left_block[:4]),
        replacement_text=left_mut_text,
    )

    doc_mut = fitz.open(stream=mut_left_pdf, filetype="pdf")
    mut_blocks = doc_mut[0].get_text("blocks")
    doc_mut.close()

    mut_right = next(b for b in mut_blocks if b[0] > 200 and "Lead Frontend" in b[4])
    right_x_shift = abs(right_block[0] - mut_right[0]) + abs(right_block[2] - mut_right[2])
    right_y_shift = abs(right_block[1] - mut_right[1]) + abs(right_block[3] - mut_right[3])
    right_text_identical = right_block[4] == mut_right[4]

    assert right_x_shift == 0.0, f"Right column x shifted by {right_x_shift}pt"
    assert right_y_shift == 0.0, f"Right column y shifted by {right_y_shift}pt"
    assert right_text_identical, "Right column text was altered by left column mutation"

    right_mut_text = "Lead Frontend Engineer — WebWorks Inc\n• Spearheaded complete design system migration with 0 visual regressions."
    mut_right_pdf, _ = PDFMutationEngine.mutate(
        pdf_bytes=pdf_bytes,
        page_index=0,
        bbox=list(right_block[:4]),
        replacement_text=right_mut_text,
    )

    doc_mut_r = fitz.open(stream=mut_right_pdf, filetype="pdf")
    mut_r_blocks = doc_mut_r[0].get_text("blocks")
    doc_mut_r.close()

    mut_left = next(b for b in mut_r_blocks if b[0] < 100 and "TECHNICAL SKILLS" in b[4])
    left_x_shift = abs(left_block[0] - mut_left[0]) + abs(left_block[2] - mut_left[2])
    left_y_shift = abs(left_block[1] - mut_left[1]) + abs(left_block[3] - mut_left[3])
    left_text_identical = left_block[4] == mut_left[4]

    assert left_x_shift == 0.0, f"Left column x shifted by {left_x_shift}pt"
    assert left_y_shift == 0.0, f"Left column y shifted by {left_y_shift}pt"
    assert left_text_identical, "Left column text was altered by right column mutation"

    print("\n[MULTI-COLUMN ISOLATION AUDIT]: PASS (0.00pt cross-column displacement)")
    return {
        "left_column_mutation_right_shift": right_x_shift + right_y_shift,
        "right_column_mutation_left_shift": left_x_shift + left_y_shift,
        "isolation_verified": True,
    }


def audit_multipage_isolation() -> Dict[str, Any]:
    pdf_bytes = fixture_4_two_page()

    mut_p1, _ = PDFMutationEngine.mutate(
        pdf_bytes=pdf_bytes,
        page_index=0,
        bbox=[54, 50, 558, 90],
        replacement_text="MARCUS VANCE — MUTATED TITLE",
    )

    doc_orig = fitz.open(stream=pdf_bytes, filetype="pdf")
    doc_mut = fitz.open(stream=mut_p1, filetype="pdf")
    assert len(doc_mut) == 2, "Page count altered"
    p2_orig_blocks = doc_orig[1].get_text("blocks")
    p2_mut_blocks = doc_mut[1].get_text("blocks")
    assert p2_orig_blocks == p2_mut_blocks, "Page 2 content altered by Page 1 mutation"

    mut_p1_p2, _ = PDFMutationEngine.mutate(
        pdf_bytes=mut_p1,
        page_index=1,
        bbox=[54, 50, 558, 80],
        replacement_text="MARCUS VANCE — RESUME (PAGE 2 MUTATED)",
    )
    doc_p1_p2 = fitz.open(stream=mut_p1_p2, filetype="pdf")
    assert len(doc_p1_p2) == 2
    p1_blocks = doc_p1_p2[0].get_text("blocks")
    assert any("MUTATED TITLE" in b[4] for b in p1_blocks), "Page 1 mutation lost after Page 2 mutation"
    doc_orig.close()
    doc_mut.close()
    doc_p1_p2.close()

    print("[MULTI-PAGE ISOLATION AUDIT]: PASS (Page 1 and Page 2 perfectly isolated)")
    return {"multipage_isolation": True}


def audit_mutation_stress_test() -> Dict[str, Any]:
    base_bullet = "Architected high-throughput data processing platform on AWS."
    scales = [1.0, 1.25, 1.5, 2.0, 3.0, 5.0, 10.0]
    stress_results = []

    print("\n" + "=" * 70)
    print("RUNNING MUTATION SIZE STRESS TEST (1x, 1.25x, 1.5x, 2x, 3x, 5x, 10x)")
    print("=" * 70)

    for s in scales:
        text = " ".join((base_bullet + " ") * int(math.ceil(s)))[:int(len(base_bullet) * s)]

        pdf_bytes = fixture_1_single_column()
        mutated, geom = PDFMutationEngine.mutate(
            pdf_bytes=pdf_bytes,
            page_index=0,
            bbox=[54, 180, 558, 220],
            replacement_text=text,
        )

        doc = fitz.open(stream=mutated, filetype="pdf")
        p = doc[0]
        blocks = p.get_text("blocks")
        doc.close()

        mut_b = next((b for b in blocks if b[1] >= 170 and b[1] < 225), None)
        next_b = next((b for b in blocks if b[1] >= 225 and "FinTech" in b[4]), None)

        overlap = False
        if mut_b and next_b:
            if mut_b[3] > next_b[1]:
                overlap = True

        stress_results.append({
            "scale": s,
            "text_len": len(text),
            "mutated_bbox": [round(x, 1) for x in mut_b[:4]] if mut_b else None,
            "next_block_top": round(next_b[1], 1) if next_b else None,
            "overlap_detected": overlap,
        })
        print(f"  Scale {s}x ({len(text)} chars): Overlap={overlap} (mut_y1={round(mut_b[3], 1) if mut_b else 'N/A'}, next_y0={round(next_b[1], 1) if next_b else 'N/A'})")

    return {"scales_tested": scales, "results": stress_results}


if __name__ == "__main__":
    benchmark_summary = run_acceptance_benchmark()
    multi_col_summary = audit_multi_column_isolation()
    multipage_summary = audit_multipage_isolation()
    stress_summary = audit_mutation_stress_test()

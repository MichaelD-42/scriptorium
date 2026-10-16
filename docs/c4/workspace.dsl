/*
 * C4 model of the scriptorium plugin. Render with Structurizr Lite:
 *   docker run -it --rm -p 8080:8080 -v "$PWD/docs/c4:/usr/local/structurizr" structurizr/lite
 * The prose behind these diagrams is docs/architecture.md; the scripts and
 * file schemas are docs/tooling.md.
 */
workspace "scriptorium" "Document-to-Markdown extraction pipeline run as a Claude Code plugin." {

    !identifiers hierarchical

    model {
        user = person "User" "Drops documents into input/ and runs /scriptorium:extract."

        claude = softwareSystem "Claude model" "Runs the orchestrator session and its subagents; reads page images for vision transcription, image descriptions and grading." "External"
        tesseract = softwareSystem "Tesseract" "Local OCR engine plus language packs." "External"
        libreoffice = softwareSystem "LibreOffice" "Headless pptx-to-PDF conversion, only to render slides." "External"

        scriptorium = softwareSystem "scriptorium" "Turns PDF, pptx, docx, xlsx, html and image documents into graded Markdown, HTML, OKF, md-tree or ReqIF." {
            orchestrator = container "Orchestrator" "Drives the queue loop: triage, parallel extract batches, merge/assemble/gates, parallel grade batches, decide pass / escalate / needs-human. Reads only script stdout, state.json and grade-report.json (context-rot rule)." "Claude Code slash command (commands/extract.md)" "Agent"
            extractor = container "Extractor" "Extracts one page batch at its assigned tier (text, OCR, vision) plus images, captions, figure text and mermaid. Writes only its own pages' shards." "Claude Code subagent, one per batch, in parallel" "Agent"
            grader = container "Grader" "Grades one page batch against the rubric by comparing rendered pages to the assembled output. Writes only its own pages' grade shards." "Claude Code subagent, one per batch, in parallel" "Agent"

            scripts = container "Skill scripts" "Deterministic CLI steps, one skill per tier or format." "Python 3.11+, uv" {
                triage = component "Triage" "Per format: page split, tier per page, loop size. PDF also: preflight, furniture, TOC, body font size." "pdf/pptx/docx/xlsx/html/image-triage"
                render = component "Render" "Page or region to PNG; pptx via LibreOffice." "render-pages"
                extractText = component "Native extract" "Text-tier body shards: headings, paragraphs, lists, tables." "extract-text, pptx/docx/xlsx/html-extract"
                ocr = component "OCR" "OCR-tier body shards; lands vision transcriptions." "ocr-page"
                images = component "Image extract" "Bitmaps and vector figure regions, captions, figure text; agent-written descriptions and mermaid." "extract-images"
                merge = component "Merge + assemble" "Shards to elements.json (page-break joins, furniture removal), then the output format." "assemble-output"
                gates = component "Gates + grade merge" "Structural gates, text-mode grading, grade shards to grade-report.json." "grade-output"
            }
            lib = container "Shared library" "Paths, shard I/O, furniture, figures, glyph repair, TOC." "Python package (lib/)"

            state = container "Queue state" "One entry per input document: status, attempt, escalated pages, OCR language, warnings." "runs/state.json" "Store"
            work = container "Work area" "triage.json, toc.json, page PNGs, per-page shards, elements.json." "work/<doc>/" "Store"
            output = container "Output area" "Assembled document, assets, grade shards, grade-report.json, optional zip." "output/<doc>/" "Store"
        }

        user -> scriptorium.orchestrator "Runs /scriptorium:extract"
        user -> scriptorium.output "Reads results and needs-human reports"
        scriptorium.orchestrator -> claude "Runs on"
        scriptorium.extractor -> claude "Runs on; vision reads"
        scriptorium.grader -> claude "Runs on; vision reads"

        scriptorium.orchestrator -> scriptorium.state "Reads and updates"
        scriptorium.orchestrator -> scriptorium.extractor "Spawns one per page batch, in parallel"
        scriptorium.orchestrator -> scriptorium.grader "Spawns one per page batch, in parallel"
        scriptorium.orchestrator -> scriptorium.scripts.triage "Runs, reads compact stdout"
        scriptorium.orchestrator -> scriptorium.scripts.merge "Runs"
        scriptorium.orchestrator -> scriptorium.scripts.gates "Runs, reads grade-report.json"

        scriptorium.extractor -> scriptorium.scripts.render "Runs"
        scriptorium.extractor -> scriptorium.scripts.extractText "Runs"
        scriptorium.extractor -> scriptorium.scripts.ocr "Runs"
        scriptorium.extractor -> scriptorium.scripts.images "Runs"
        scriptorium.grader -> scriptorium.scripts.render "Runs"
        scriptorium.grader -> scriptorium.scripts.gates "Writes grade shards with"

        scriptorium.scripts -> scriptorium.lib "Imports"
        scriptorium.scripts.triage -> scriptorium.work "Writes triage.json, toc.json"
        scriptorium.scripts.render -> scriptorium.work "Writes page PNGs"
        scriptorium.scripts.render -> libreoffice "Converts pptx with"
        scriptorium.scripts.extractText -> scriptorium.work "Writes text shards"
        scriptorium.scripts.ocr -> scriptorium.work "Writes ocr/vision shards"
        scriptorium.scripts.ocr -> tesseract "OCRs with"
        scriptorium.scripts.images -> scriptorium.work "Writes image shards"
        scriptorium.scripts.images -> scriptorium.output "Writes assets"
        scriptorium.scripts.merge -> scriptorium.work "Reads shards, writes elements.json"
        scriptorium.scripts.merge -> scriptorium.output "Writes the assembled document"
        scriptorium.scripts.gates -> scriptorium.output "Writes grade shards and grade-report.json"
    }

    views {
        systemContext scriptorium "Context" {
            include *
            autoLayout lr
        }

        container scriptorium "Containers" {
            include *
            autoLayout lr
        }

        component scriptorium.scripts "Scripts" {
            include *
            autoLayout lr
        }

        dynamic scriptorium "Attempt" "One extraction attempt for one document." {
            user -> scriptorium.orchestrator "Runs /scriptorium:extract"
            scriptorium.orchestrator -> scriptorium.state "Picks the next pending or retrying document"
            scriptorium.orchestrator -> scriptorium.extractor "Spawns one per page batch (after triage on attempt 0)"
            scriptorium.extractor -> claude "Transcribes pages that OCR could not read"
            scriptorium.orchestrator -> scriptorium.grader "Spawns one per page batch (after merge, assemble, gates)"
            scriptorium.grader -> claude "Compares rendered pages to the output"
            scriptorium.orchestrator -> scriptorium.state "Records passed, retrying with escalated pages, or needs-human"
            autoLayout lr
        }

        styles {
            element "Element" {
                background #2f4858
                color #ffffff
                shape RoundedBox
            }
            element "Person" {
                background #1b3a4b
                shape Person
            }
            element "External" {
                background #8a8f94
            }
            element "Agent" {
                background #33658a
                shape Robot
            }
            element "Store" {
                background #86bbd8
                color #10212b
                shape Cylinder
            }
        }
    }
}

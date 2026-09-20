/* ==================================================================
   script.js - AI Resume Analyzer
   ==================================================================
   Front-end JavaScript.

   In Phase 1 it does three small but useful things:
     1. Shows the name of the PDF the user picked.
     2. Checks on the browser side that the file is a PDF and under 5 MB.
        (The server will check AGAIN in Phase 2 - browser checks can be
         bypassed, so they are for convenience, never for security.)
     3. Counts the characters typed in the Job Description box.

   Everything is wrapped in DOMContentLoaded so the code runs only after
   the HTML elements actually exist on the page.
   ================================================================== */

document.addEventListener("DOMContentLoaded", function () {

    // ---------------- Configuration ----------------
    const MAX_FILE_MB = 5;                       // must match app.py
    const MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024;

    // ---------------- "Save as PDF" button ----------------
    // Wired here rather than with onclick="" in the HTML, because our
    // Content-Security-Policy blocks inline event handlers.
    const printBtn = document.getElementById("printBtn");
    if (printBtn) {
        printBtn.addEventListener("click", function () {
            window.print();
        });
    }

    // ---------------- Grab the HTML elements ----------------
    const fileInput   = document.getElementById("resumeFile");
    const dropzone    = document.getElementById("dropzone");
    const zoneTitle   = document.getElementById("dropzoneTitle");
    const feedback    = document.getElementById("fileFeedback");
    const analyzeBtn  = document.getElementById("analyzeBtn");
    const jdBox       = document.getElementById("jobDescription");
    const jdCount     = document.getElementById("jdCount");
    const form        = document.getElementById("analyzeForm");

    // If we are on a page without the form (e.g. the error page), stop here.
    if (!fileInput || !dropzone) {
        return;
    }

    /**
     * Turn a size in bytes into something human readable, e.g. "248 KB".
     */
    function formatSize(bytes) {
        if (bytes < 1024) return bytes + " B";
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
        return (bytes / (1024 * 1024)).toFixed(2) + " MB";
    }

    /**
     * Show a message under the dropzone.
     * type is either "ok" or "error" and only changes the colour.
     */
    function showFeedback(text, type) {
        feedback.textContent = text;
        feedback.className = "form-hint " + (type === "ok" ? "text-ok" : "text-error");
    }

    /**
     * Validate the chosen file and update the UI accordingly.
     */
    function handleFile(file) {
        // Reset the box to its default look before deciding.
        dropzone.classList.remove("has-file");
        analyzeBtn.disabled = true;

        if (!file) {
            zoneTitle.textContent = "Click to choose a PDF file";
            feedback.textContent = "";
            return;
        }

        // --- Check 1: is it really a PDF? ---
        const isPdfType = file.type === "application/pdf";
        const isPdfName = file.name.toLowerCase().endsWith(".pdf");
        if (!isPdfType && !isPdfName) {
            showFeedback("Only PDF files are allowed. Please choose a .pdf resume.", "error");
            zoneTitle.textContent = "Click to choose a PDF file";
            fileInput.value = "";          // clear the invalid selection
            return;
        }

        // --- Check 2: is the file empty? ---
        if (file.size === 0) {
            showFeedback("That file is empty. Please choose a different PDF.", "error");
            fileInput.value = "";
            return;
        }

        // --- Check 3: is it too big? ---
        if (file.size > MAX_FILE_BYTES) {
            showFeedback(
                "File is " + formatSize(file.size) +
                ". Maximum allowed size is " + MAX_FILE_MB + " MB.", "error");
            fileInput.value = "";
            return;
        }

        // --- All checks passed ---
        dropzone.classList.add("has-file");
        zoneTitle.textContent = file.name;
        showFeedback("Ready to analyze (" + formatSize(file.size) + ")", "ok");

        // The file looks good, so let the user submit the form.
        analyzeBtn.disabled = false;
    }

    // ---------------- Event: user picked a file ----------------
    fileInput.addEventListener("change", function () {
        handleFile(fileInput.files[0]);
    });

    // ---------------- Events: drag and drop ----------------
    // "dragover" fires continuously while a file hovers over the box.
    // preventDefault() stops the browser from just opening the PDF.
    ["dragenter", "dragover"].forEach(function (eventName) {
        dropzone.addEventListener(eventName, function (event) {
            event.preventDefault();
            dropzone.classList.add("dragover");
        });
    });

    ["dragleave", "drop"].forEach(function (eventName) {
        dropzone.addEventListener(eventName, function (event) {
            event.preventDefault();
            dropzone.classList.remove("dragover");
        });
    });

    dropzone.addEventListener("drop", function (event) {
        const dropped = event.dataTransfer.files;
        if (dropped && dropped.length > 0) {
            // Put the dropped file into the real <input> so the form can send it.
            fileInput.files = dropped;
            handleFile(dropped[0]);
        }
    });

    // ---------------- Job description character counter ----------------
    if (jdBox && jdCount) {
        jdBox.addEventListener("input", function () {
            jdCount.textContent = jdBox.value.trim().length;
        });
    }

    // ---------------- Form submit ----------------
    // The form now really posts to /upload in app.py. We do NOT call
    // preventDefault() any more - we let the browser send the file.
    // We only improve the experience: block an empty submit and show a
    // "please wait" state, because reading a PDF takes a moment.
    if (form) {
        form.addEventListener("submit", function (event) {

            // Last-second guard: no file chosen.
            if (!fileInput.files || fileInput.files.length === 0) {
                event.preventDefault();
                showFeedback("Please choose a PDF file first.", "error");
                return;
            }

            // Show a spinner and stop double submits (an impatient user
            // clicking twice would upload the file twice).
            analyzeBtn.disabled = true;
            analyzeBtn.innerHTML =
                '<span class="spinner-border spinner-border-sm me-2"></span>' +
                'Reading your resume...';
        });
    }

    // ---------------- Restore the button on "Back" ----------------
    // When the user presses the browser Back button, some browsers restore
    // the page from cache with the button still disabled and spinning.
    // pageshow with event.persisted tells us that happened, so we reset it.
    window.addEventListener("pageshow", function (event) {
        if (event.persisted && analyzeBtn) {
            analyzeBtn.disabled = fileInput.files.length === 0;
            analyzeBtn.innerHTML = '<i class="bi bi-magic"></i> Analyze Resume';
        }
    });
});

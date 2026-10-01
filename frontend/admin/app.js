const API_BASE = window.SUPPORTAI_CONFIG.API_URL.replace(/\/+$/, "");

const state = {
    token: localStorage.getItem("admin_token"),
    user: null,
};


// ============================================================
// DOM ELEMENTS
// ============================================================

const authScreen =
    document.getElementById("auth-screen");

const dashboard =
    document.getElementById("dashboard");

const loginForm =
    document.getElementById("login-form");

const loginError =
    document.getElementById("login-error");

const passwordInput =
    document.getElementById("password");

const adminPasswordToggle =
    document.getElementById("adminPasswordToggle");

const adminHelpBtn =
    document.getElementById("adminHelpBtn");

const adminHelpModal =
    document.getElementById("adminHelpModal");

const closeAdminHelpModal =
    document.getElementById("closeAdminHelpModal");

const adminHelpBackBtn =
    document.getElementById("adminHelpBackBtn");

const adminName =
    document.getElementById("admin-name");

const logoutButton =
    document.getElementById("logout-button");

const documentFile =
    document.getElementById("document-file");

const uploadButton =
    document.getElementById("upload-button");

const uploadStatus =
    document.getElementById("upload-status");

const documentsBody =
    document.getElementById("documents-body");

const refreshButton =
    document.getElementById("refresh-button");


// ============================================================
// SUPPORT CASES DOM ELEMENTS
// ============================================================

const casesBody =
    document.getElementById("cases-body");

const refreshCasesButton =
    document.getElementById("refresh-cases-button");


// ============================================================
// AUTH HELPERS
// ============================================================

function showAuthScreen() {

    authScreen.classList.remove("hidden");

    dashboard.classList.add("hidden");
}


function showDashboard() {

    authScreen.classList.add("hidden");

    dashboard.classList.remove("hidden");
}


function setLoginError(message) {

    loginError.textContent =
        message || "";
}


// ============================================================
// LOGOUT
// ============================================================

function logout() {

    localStorage.removeItem("admin_token");

    state.token = null;
    state.user = null;

    showAuthScreen();
}


if (logoutButton) {

    logoutButton.addEventListener(
        "click",
        logout
    );
}


// ============================================================
// API HELPER
// ============================================================

async function apiRequest(
    endpoint,
    options = {}
) {
    const headers = {
        ...(options.headers || {})
    };

    if (state.token) {
        headers.Authorization =
            `Bearer ${state.token}`;
    }

    let response;
    try {
        response = await fetch(
            `${API_BASE}${endpoint}`,
            {
                ...options,
                headers
            }
        );
    } catch (netErr) {
        throw new Error(
            `Unable to connect to the backend server at ${API_BASE}. Please ensure the server is running.`
        );
    }

    let data = null;
    try {
        data = await response.json();
    } catch {
        data = null;
    }

    if (!response.ok) {
        if (response.status === 401) {
            logout();
        }

        let message = `Request failed with status ${response.status}`;
        if (typeof data?.detail === "string") {
            message = data.detail;
        } else if (Array.isArray(data?.detail) && data.detail.length > 0) {
            message = data.detail[0]?.msg || message;
        } else if (response.status === 403) {
            message = "Access denied: You do not have permission to perform this action.";
        }

        throw new Error(message);
    }

    return data;
}


// ============================================================
// LOGIN
// ============================================================

if (loginForm) {
    loginForm.addEventListener(
        "submit",
        async (event) => {
            event.preventDefault();
            setLoginError("");

            const emailInput = document.getElementById("email");
            const passInput = document.getElementById("password");
            const email = (emailInput?.value || "").trim();
            const password = passInput?.value || "";

            const loginButton = document.getElementById("login-button");

            if (!email || !password) {
                setLoginError("Please enter your administrator email and password.");
                return;
            }

            if (loginButton) {
                loginButton.disabled = true;
                loginButton.innerHTML = "<span>Signing into Dashboard...</span>";
            }

            try {
                let response;
                try {
                    response = await fetch(
                        `${API_BASE}/auth/login`,
                        {
                            method: "POST",
                            headers: {
                                "Content-Type": "application/json",
                            },
                            body: JSON.stringify({
                                email,
                                password,
                            }),
                        }
                    );
                } catch (netErr) {
                    throw new Error(
                        `Unable to connect to the backend server at ${API_BASE}. Please ensure the backend is running.`
                    );
                }

                let data = null;
                try {
                    data = await response.json();
                } catch {
                    data = null;
                }

                if (!response.ok) {
                    if (response.status === 401) {
                        throw new Error(
                            (typeof data?.detail === "string" && data.detail) ||
                            "Incorrect email or password."
                        );
                    }
                    if (response.status === 403) {
                        throw new Error(
                            (typeof data?.detail === "string" && data.detail) ||
                            "Access denied: This account does not have administrator privileges."
                        );
                    }
                    if (response.status === 422) {
                        let msg = "Invalid input format. Please check your email and password.";
                        if (Array.isArray(data?.detail) && data.detail.length > 0) {
                            msg = data.detail[0]?.msg || msg;
                        } else if (typeof data?.detail === "string") {
                            msg = data.detail;
                        }
                        throw new Error(msg);
                    }
                    if (response.status === 429) {
                        throw new Error(
                            (typeof data?.detail === "string" && data.detail) ||
                            "Too many requests. Please wait a moment and try again."
                        );
                    }
                    if (response.status >= 500) {
                        throw new Error(
                            "The server encountered an internal error. Please try again later."
                        );
                    }
                    throw new Error(
                        (typeof data?.detail === "string" && data.detail) ||
                        `Sign in failed (HTTP ${response.status}).`
                    );
                }

                if (!data || !data.access_token) {
                    throw new Error("Invalid response received from authentication server.");
                }

                if (data.role && data.role !== "admin") {
                    throw new Error("This account does not have administrator access.");
                }

                state.token = data.access_token;
                localStorage.setItem("admin_token", state.token);

                await loadCurrentUser();

                if (state.user && state.user.role !== "admin") {
                    logout();
                    throw new Error("This account does not have administrator access.");
                }

                showDashboard();

                await loadDocuments();
                await loadSupportCases();

            } catch (error) {
                setLoginError(
                    error.message || "Unable to sign in. Please verify your credentials."
                );
            } finally {
                if (loginButton) {
                    loginButton.disabled = false;
                    loginButton.innerHTML = '<span>Sign into Dashboard</span><span class="btn-arrow">→</span>';
                }
            }
        }
    );
}


// ============================================================
// PASSWORD VISIBILITY & RECOVERY CONTROLS
// ============================================================

if (adminPasswordToggle && passwordInput) {
    adminPasswordToggle.addEventListener("click", (e) => {
        e.preventDefault();
        const isPassword = passwordInput.type === "password";
        passwordInput.type = isPassword ? "text" : "password";
        adminPasswordToggle.setAttribute("aria-label", isPassword ? "Hide password" : "Show password");
        adminPasswordToggle.setAttribute("title", isPassword ? "Hide password" : "Show password");
        const eyeOpen = adminPasswordToggle.querySelector(".eye-open");
        const eyeClosed = adminPasswordToggle.querySelector(".eye-closed");
        if (eyeOpen && eyeClosed) {
            eyeOpen.classList.toggle("hidden", isPassword);
            eyeClosed.classList.toggle("hidden", !isPassword);
        }
    });
}

function openAdminHelpModal() {
    if (adminHelpModal) {
        adminHelpModal.classList.remove("hidden");
    }
}

function closeAdminHelp() {
    if (adminHelpModal) {
        adminHelpModal.classList.add("hidden");
    }
}

if (adminHelpBtn) {
    adminHelpBtn.addEventListener("click", openAdminHelpModal);
}

if (closeAdminHelpModal) {
    closeAdminHelpModal.addEventListener("click", closeAdminHelp);
}

if (adminHelpBackBtn) {
    adminHelpBackBtn.addEventListener("click", closeAdminHelp);
}

if (adminHelpModal) {
    adminHelpModal.addEventListener("click", (e) => {
        if (e.target === adminHelpModal) {
            closeAdminHelp();
        }
    });
}

document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && adminHelpModal && !adminHelpModal.classList.contains("hidden")) {
        closeAdminHelp();
    }
});


// ============================================================
// CURRENT USER
// ============================================================

async function loadCurrentUser() {

    const user =
        await apiRequest(
            "/auth/me"
        );


    state.user = user;


    adminName.textContent =
        user.name ||
        user.email;
}


// ============================================================
// LOAD DOCUMENTS
// ============================================================

async function loadDocuments() {

    documentsBody.innerHTML = `
        <tr>
            <td
                colspan="5"
                class="empty-state"
            >
                Loading documents...
            </td>
        </tr>
    `;


    try {

        const documents =
            await apiRequest(
                "/admin/documents"
            );


        renderDocuments(documents);


    } catch (error) {

        documentsBody.innerHTML = `
            <tr>
                <td
                    colspan="5"
                    class="empty-state error-message"
                >
                    ${escapeHtml(
                        error.message
                    )}
                </td>
            </tr>
        `;
    }
}


// ============================================================
// RENDER DOCUMENTS
// ============================================================

function renderDocuments(documents) {

    if (
        !documents ||
        documents.length === 0
    ) {

        documentsBody.innerHTML = `
            <tr>
                <td
                    colspan="5"
                    class="empty-state"
                >
                    No documents uploaded yet.
                </td>
            </tr>
        `;

        return;
    }


    documentsBody.innerHTML =
        documents
            .map(
                (document) => {

                    const uploadedDate =
                        document.upload_date
                            ? new Date(
                                document.upload_date
                            ).toLocaleString()
                            : "-";


                    const statusClass =
                        document.status ===
                        "indexed"

                            ? "status-indexed"

                            : document.status ===
                              "failed"

                                ? "status-failed"

                                : "status-processing";


                    return `
                        <tr>

                            <td>
                                <strong>
                                    ${escapeHtml(
                                        document.filename
                                    )}
                                </strong>
                            </td>


                            <td>
                                <span
                                    class="status-badge ${statusClass}"
                                >
                                    ${escapeHtml(
                                        document.status
                                    )}
                                </span>
                            </td>


                            <td>
                                ${document.chunk_count ?? 0}
                            </td>


                            <td>
                                ${uploadedDate}
                            </td>


                            <td>

                                <button
                                    class="delete-button"
                                    data-document-id="${escapeHtml(
                                        document.id
                                    )}"
                                >
                                    Delete
                                </button>

                            </td>

                        </tr>
                    `;
                }
            )
            .join("");

    if (documentsBody && !documentsBody.dataset.listenerBound) {
        documentsBody.dataset.listenerBound = "true";
        documentsBody.addEventListener("click", (event) => {
            const btn = event.target.closest(".delete-button");
            if (btn && btn.dataset.documentId) {
                deleteDocument(btn.dataset.documentId);
            }
        });
    }
}


// ============================================================
// UPLOAD DOCUMENT
// ============================================================

if (uploadButton) {

    uploadButton.addEventListener(
        "click",
        async () => {

            uploadStatus.textContent = "";


            const file =
                documentFile.files[0];


            if (!file) {

                uploadStatus.textContent =
                    "Please choose a PDF, TXT, or MD file.";

                return;
            }


            const allowedExtensions = [
                ".pdf",
                ".txt",
                ".md",
            ];


            const filename =
                file.name.toLowerCase();


            const supported =
                allowedExtensions.some(
                    extension =>
                        filename.endsWith(
                            extension
                        )
                );


            if (!supported) {

                uploadStatus.textContent =
                    "Only PDF, TXT, and MD files are supported.";

                return;
            }


            const formData =
                new FormData();


            formData.append(
                "file",
                file
            );


            uploadButton.disabled = true;

            uploadButton.textContent =
                "Uploading & indexing...";


            try {

                const response =
                    await apiRequest(
                        "/admin/documents/upload",
                        {
                            method: "POST",
                            body: formData,
                        }
                    );


                uploadStatus.textContent =
                    `✓ ${response.filename} indexed successfully. ` +
                    `${response.chunk_count} chunk(s) created.`;


                documentFile.value = "";


                await loadDocuments();


            } catch (error) {

                uploadStatus.textContent =
                    `Upload failed: ${error.message}`;


            } finally {

                uploadButton.disabled = false;

                uploadButton.textContent =
                    "Upload & Index";
            }
        }
    );
}


// ============================================================
// DELETE DOCUMENT
// ============================================================

async function deleteDocument(
    documentId
) {

    const confirmed =
        window.confirm(
            "Are you sure you want to delete this document?"
        );


    if (!confirmed) {
        return;
    }


    try {

        await apiRequest(
            `/admin/documents/${documentId}`,
            {
                method: "DELETE",
            }
        );


        await loadDocuments();


    } catch (error) {

        alert(
            `Unable to delete document: ${error.message}`
        );
    }
}


// ============================================================
// SUPPORT CASES
// ============================================================

async function loadSupportCases() {

    if (!casesBody) {
        return;
    }


    casesBody.innerHTML = `
        <tr>
            <td
                colspan="6"
                class="empty-state"
            >
                Loading support cases...
            </td>
        </tr>
    `;


    try {

        const tickets =
            await apiRequest(
                "/tickets"
            );


        renderSupportCases(tickets);


    } catch (error) {

        casesBody.innerHTML = `
            <tr>
                <td
                    colspan="6"
                    class="empty-state error-message"
                >
                    ${escapeHtml(
                        error.message
                    )}
                </td>
            </tr>
        `;
    }
}


// ============================================================
// RENDER SUPPORT CASES
// ============================================================

function renderSupportCases(tickets) {

    if (
        !tickets ||
        tickets.length === 0
    ) {

        casesBody.innerHTML = `
            <tr>
                <td
                    colspan="6"
                    class="empty-state"
                >
                    No support cases found.
                </td>
            </tr>
        `;

        return;
    }


    casesBody.innerHTML =
        tickets
            .map(
                (ticket) => {

                    const priority =
                        ticket.priority ||
                        "medium";


                    const status =
                        ticket.status ||
                        "open";


                    const ticketId =
                        ticket.ticket_id ||
                        ticket.id ||
                        "-";


                    const encodedTicketId =
                        encodeURIComponent(
                            ticketId
                        );


                    return `
                        <tr>

                            <td>
                                <strong>
                                    ${escapeHtml(
                                        ticketId
                                    )}
                                </strong>
                            </td>


                            <td>
                                ${escapeHtml(
                                    ticket.order_id ||
                                    "-"
                                )}
                            </td>


                            <td class="case-issue">
                                ${escapeHtml(
                                    ticket.issue ||
                                    "-"
                                )}
                            </td>


                            <td>

                                <span
                                    class="priority-badge priority-${escapeHtml(
                                        priority
                                    )}"
                                >
                                    ${escapeHtml(
                                        priority
                                    )}
                                </span>

                            </td>


                            <td>

                                <select
                                    class="case-status-select"
                                    id="case-status-${encodedTicketId}"
                                >
                                    <option value="open" ${status === "open" ? "selected" : ""}>Open</option>
                                    <option value="investigating" ${status === "investigating" ? "selected" : ""}>Investigating</option>
                                    <option value="in_progress" ${status === "in_progress" ? "selected" : ""}>In Progress</option>
                                    <option value="escalated" ${status === "escalated" ? "selected" : ""}>Escalated</option>
                                    <option value="resolved" ${status === "resolved" ? "selected" : ""}>Resolved</option>
                                    <option value="closed" ${status === "closed" ? "selected" : ""}>Closed</option>
                                    ${
                                        !["open", "investigating", "in_progress", "escalated", "resolved", "closed"].includes(status)
                                            ? `<option value="${escapeHtml(status)}" selected>${escapeHtml(status)}</option>`
                                            : ""
                                    }
                                </select>

                            </td>


                            <td>

                                <button
                                    class="case-update-button"
                                    data-ticket-id="${encodedTicketId}"
                                >
                                    Update
                                </button>

                            </td>

                        </tr>
                    `;
                }
            )
            .join("");

    if (casesBody && !casesBody.dataset.listenerBound) {
        casesBody.dataset.listenerBound = "true";
        casesBody.addEventListener("click", (event) => {
            const btn = event.target.closest(".case-update-button");
            if (btn && btn.dataset.ticketId) {
                updateSupportCase(decodeURIComponent(btn.dataset.ticketId));
            }
        });
    }
}


// ============================================================
// UPDATE SUPPORT CASE
// ============================================================

async function updateSupportCase(
    encodedTicketId
) {

    const ticketId =
        decodeURIComponent(
            encodedTicketId
        );


    const statusElement =
        document.getElementById(
            `case-status-${encodedTicketId}`
        );


    if (!statusElement) {
        return;
    }


    const newStatus =
        statusElement.value;


    try {

        await apiRequest(
            `/tickets/${encodeURIComponent(
                ticketId
            )}`,
            {
                method: "PATCH",

                headers: {
                    "Content-Type":
                        "application/json",
                },

                body: JSON.stringify({
                    status: newStatus,
                }),
            }
        );


        await loadSupportCases();


    } catch (error) {

        alert(
            `Unable to update support case: ${error.message}`
        );
    }
}


// ============================================================
// REFRESH DOCUMENTS
// ============================================================

if (refreshButton) {

    refreshButton.addEventListener(
        "click",
        loadDocuments
    );
}


// ============================================================
// REFRESH SUPPORT CASES
// ============================================================

if (refreshCasesButton) {

    refreshCasesButton.addEventListener(
        "click",
        loadSupportCases
    );
}


// ============================================================
// HTML ESCAPING
// ============================================================

function escapeHtml(value) {

    return String(value)
        .replaceAll(
            "&",
            "&amp;"
        )
        .replaceAll(
            "<",
            "&lt;"
        )
        .replaceAll(
            ">",
            "&gt;"
        )
        .replaceAll(
            '"',
            "&quot;"
        )
        .replaceAll(
            "'",
            "&#039;"
        );
}


// ============================================================
// STARTUP
// ============================================================

async function initialize() {

    if (!state.token) {

        showAuthScreen();

        return;
    }


    try {

        await loadCurrentUser();


        if (!state.user || state.user.role !== "admin") {
            const isCustomer = state.user && state.user.role === "customer";
            logout();
            if (isCustomer) {
                window.location.replace("../demo-customer/");
                return;
            }
            setLoginError("Access denied: This account does not have administrator access.");
            return;
        }


        showDashboard();


        await loadDocuments();

        await loadSupportCases();


    } catch (error) {

        logout();
    }
}


// ============================================================
// BACK TO SUPPORTAI CUSTOMER LANDING PAGE
// ============================================================

const closeAuthModal =
    document.getElementById(
        "closeAuthModal"
    );


if (closeAuthModal) {

    closeAuthModal.addEventListener(
        "click",
        function () {

            window.location.href =
                "../demo-customer/";
        }
    );
}


// ============================================================
// START APPLICATION
// ============================================================

initialize();

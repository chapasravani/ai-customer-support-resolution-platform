/* =========================================================
   SUPPORTAI CUSTOMER FRONTEND
   Complete customer UI JavaScript
   Connects to the existing FastAPI + ADK backend.
   ========================================================= */


/* =========================================================
   CONFIGURATION
   ========================================================= */

const API_BASE_URL = window.SUPPORTAI_CONFIG.API_URL.replace(/\/+$/, "");


/* =========================================================
   APPLICATION STATE
   ========================================================= */

const rawStoredUser = typeof localStorage !== "undefined" ? localStorage.getItem("supportai_user") : null;
let initialUser = null;
try {
    initialUser = JSON.parse(rawStoredUser || "null");
} catch {
    initialUser = null;
}
if (initialUser && initialUser.role !== "customer") {
    initialUser = null;
}

const state = {
    token: (typeof localStorage !== "undefined" && localStorage.getItem("supportai_token")) || null,

    user: initialUser,

    conversationId:
        localStorage.getItem("supportai_conversation_id") || null,

    isSending: false,

    /* Abort controller for the current in-flight fetch */
    abortController: null,

    conversations: [],

    conversationSearch: "",

    authMode: "login",

    /* Responsive and desktop sidebar state */
    sidebarCollapsed:
        (typeof localStorage !== "undefined" && localStorage.getItem("supportai_sidebar_collapsed") === "true") || false,

    sidebarMobileOpen: false,

    /* Pending conversation for rename/delete modal flows */
    _pendingRenameConversation: null,
    _pendingDeleteConversation: null
};


/* =========================================================
   DOM ELEMENTS
   ========================================================= */

const elements = {

    sidebar:
        document.getElementById("sidebar"),

    sidebarToggleBtn:
        document.getElementById("sidebarToggleBtn"),

    sidebarBackdrop:
        document.getElementById("sidebarBackdrop"),

    newChatBtn:
        document.getElementById("newChatBtn"),

    refreshConversations:
        document.getElementById("refreshConversations"),

    conversationSearch:
        document.getElementById("conversationSearch"),

    clearConversationSearch:
        document.getElementById("clearConversationSearch"),

    conversationList:
        document.getElementById("conversationList"),

    conversationTitle:
        document.getElementById("conversationTitle"),

    welcomeScreen:
        document.getElementById("welcomeScreen"),

    messagesContainer:
        document.getElementById("messagesContainer"),

    thinkingIndicator:
        document.getElementById("thinkingIndicator"),

    messageInput:
        document.getElementById("messageInput"),

    sendBtn:
        document.getElementById("sendBtn"),

    messageCounter:
        document.getElementById("messageCounter"),

    authModal:
        document.getElementById("authModal"),

    closeAuthModal:
        document.getElementById("closeAuthModal"),

    loginForm:
        document.getElementById("loginForm"),

    registerForm:
        document.getElementById("registerForm"),

    authTitle:
        document.getElementById("authTitle"),

    authSubtitle:
        document.getElementById("authSubtitle"),

    authSwitchText:
        document.getElementById("authSwitchText"),

    authSwitchBtn:
        document.getElementById("authSwitchBtn"),

    authError:
        document.getElementById("authError"),

    loginEmail:
        document.getElementById("loginEmail"),

    loginPassword:
        document.getElementById("loginPassword"),

    registerName:
        document.getElementById("registerName"),

    registerEmail:
        document.getElementById("registerEmail"),

    registerPassword:
        document.getElementById("registerPassword"),

    profileBtn:
        document.getElementById("profileBtn"),

    topProfileBtn:
        document.getElementById("topProfileBtn"),

    profileDropdown:
        document.getElementById("profileDropdown"),

    logoutBtn:
        document.getElementById("logoutBtn"),

    sidebarAvatar:
        document.getElementById("sidebarAvatar"),

    topAvatar:
        document.getElementById("topAvatar"),

    dropdownAvatar:
        document.getElementById("dropdownAvatar"),

    sidebarName:
        document.getElementById("sidebarName"),

    sidebarEmail:
        document.getElementById("sidebarEmail"),

    topUserName:
        document.getElementById("topUserName"),

    dropdownName:
        document.getElementById("dropdownName"),

    dropdownEmail:
        document.getElementById("dropdownEmail"),

    themeBtn:
        document.getElementById("themeBtn"),

    toast:
        document.getElementById("toast"),

    entryScreen:
        document.getElementById("entryScreen"),

    customerRoleBtn:
        document.getElementById("customerRoleBtn"),

    adminRoleBtn:
        document.getElementById("adminRoleBtn"),

    forgotRoleBtn:
        document.getElementById("forgotRoleBtn"),

    signupRoleBtn:
        document.getElementById("signupRoleBtn"),

    forgotInlineBtn:
        document.getElementById("forgotInlineBtn"),
forgotModal:
        document.getElementById("forgotModal"),

    closeForgotModal:
        document.getElementById("closeForgotModal"),

    forgotBackBtn:
        document.getElementById("forgotBackBtn"),

    /* Send / Stop generation */
    sendBtnWrap:
        document.getElementById("sendBtnWrap"),

    stopBtnWrap:
        document.getElementById("stopBtnWrap"),

    stopBtn:
        document.getElementById("stopBtn"),

    /* Rename conversation modal */
    renameModal:
        document.getElementById("renameModal"),

    renameInput:
        document.getElementById("renameInput"),

    renameCancelBtn:
        document.getElementById("renameCancelBtn"),

    renameConfirmBtn:
        document.getElementById("renameConfirmBtn"),

    /* Delete conversation modal */
    deleteModal:
        document.getElementById("deleteModal"),

    deleteModalDesc:
        document.getElementById("deleteModalDesc"),

    deleteCancelBtn:
        document.getElementById("deleteCancelBtn"),

    deleteConfirmBtn:
        document.getElementById("deleteConfirmBtn")
};


/* =========================================================
   INITIALIZATION
   ========================================================= */

async function fetchModelInfo() {
    const badge = document.getElementById("headerModelBadge");
    try {
        const response = await fetch(`${API_BASE_URL}/system/model-info`);
        if (response.ok) {
            const info = await response.json();
            if (badge && info.display_name) {
                badge.textContent = `● ${info.display_name}`;
                badge.title = `Provider: ${info.provider_display} | Primary Model: ${info.model}`;
                return;
            }
        }
        if (badge) {
            badge.textContent = "● AI Model — unavailable";
            badge.title = "AI model information is currently unavailable";
        }
    } catch (err) {
        console.warn("Could not load dynamic model info:", err);
        if (badge) {
            badge.textContent = "● AI Model — unavailable";
            badge.title = "AI model information is currently unavailable";
        }
    }
}

document.addEventListener("DOMContentLoaded", () => {

    setupEventListeners();

    setupTheme();

    fetchModelInfo();

    /*
     * If an existing session token exists (customer or admin), validate it against /auth/me.
     * Keep UI protected during validation to prevent UI flicker.
     */
    const storedAdminToken = (typeof localStorage !== "undefined") ? localStorage.getItem("admin_token") : null;

    if (state.token || storedAdminToken) {
        initializeAuthenticatedApp();
    } else {
        updateUserUI();
        showRoleScreen();
    }

    updateSidebarUI();
    updateMessageCounter();
    updateSendButton();

});


/* =========================================================
   RESPONSIVE & DESKTOP SIDEBAR MANAGEMENT
   ========================================================= */

function updateSidebarUI() {
    const isMobile = typeof window !== "undefined" && window.innerWidth <= 768;
    const sidebar = elements.sidebar || document.getElementById("sidebar");
    const backdrop = elements.sidebarBackdrop || document.getElementById("sidebarBackdrop");
    const toggleBtn = elements.sidebarToggleBtn || document.getElementById("sidebarToggleBtn");
    const appShell = document.querySelector(".app-shell");

    if (!sidebar) return;

    if (isMobile) {
        sidebar.classList.remove("collapsed");
        if (appShell) appShell.classList.remove("sidebar-collapsed");

        if (state.sidebarMobileOpen) {
            sidebar.classList.add("open");
            if (backdrop) backdrop.classList.remove("hidden");
            if (toggleBtn) {
                toggleBtn.setAttribute("aria-expanded", "true");
                toggleBtn.setAttribute("aria-label", "Close sidebar");
                toggleBtn.setAttribute("title", "Close sidebar");
            }
        } else {
            sidebar.classList.remove("open");
            if (backdrop) backdrop.classList.add("hidden");
            if (toggleBtn) {
                toggleBtn.setAttribute("aria-expanded", "false");
                toggleBtn.setAttribute("aria-label", "Open sidebar");
                toggleBtn.setAttribute("title", "Open sidebar");
            }
        }
    } else {
        sidebar.classList.remove("open");
        if (backdrop) backdrop.classList.add("hidden");
        state.sidebarMobileOpen = false;

        if (state.sidebarCollapsed) {
            sidebar.classList.add("collapsed");
            if (appShell) appShell.classList.add("sidebar-collapsed");
            if (toggleBtn) {
                toggleBtn.setAttribute("aria-expanded", "false");
                toggleBtn.setAttribute("aria-label", "Open sidebar");
                toggleBtn.setAttribute("title", "Open sidebar");
            }
        } else {
            sidebar.classList.remove("collapsed");
            if (appShell) appShell.classList.remove("sidebar-collapsed");
            if (toggleBtn) {
                toggleBtn.setAttribute("aria-expanded", "true");
                toggleBtn.setAttribute("aria-label", "Close sidebar");
                toggleBtn.setAttribute("title", "Close sidebar");
            }
        }
    }
}

function toggleSidebar() {
    const isMobile = typeof window !== "undefined" && window.innerWidth <= 768;
    if (isMobile) {
        state.sidebarMobileOpen = !state.sidebarMobileOpen;
    } else {
        state.sidebarCollapsed = !state.sidebarCollapsed;
        try {
            localStorage.setItem("supportai_sidebar_collapsed", state.sidebarCollapsed ? "true" : "false");
        } catch {}
    }
    updateSidebarUI();
}

function closeMobileSidebar() {
    if (state.sidebarMobileOpen) {
        state.sidebarMobileOpen = false;
        updateSidebarUI();
    }
}


/* =========================================================
   EVENT LISTENERS
   ========================================================= */

function setupEventListeners() {

    /* Entry / role selection */
    if (elements.customerRoleBtn) {
        elements.customerRoleBtn.addEventListener("click", () => {
            hideEntryScreen();
            showAuthModal();
        });
    }

    if (elements.adminRoleBtn) {
        elements.adminRoleBtn.addEventListener("click", () => {
            window.location.href = "../admin/";
        });
    }

    if (elements.signupRoleBtn) {
        elements.signupRoleBtn.addEventListener("click", () => {
            hideEntryScreen();
            if (state.authMode !== "register") {
                toggleAuthMode();
            }
            showAuthModal();
        });
    }

    if (elements.forgotRoleBtn) {
        elements.forgotRoleBtn.addEventListener("click", () => {
            hideEntryScreen();
            showForgotModal();
        });
    }

    if (elements.forgotInlineBtn) {
        elements.forgotInlineBtn.addEventListener("click", showForgotModal);
    }

    if (elements.closeForgotModal) {
        elements.closeForgotModal.addEventListener("click", closeForgotModal);
    }

    if (elements.forgotBackBtn) {
        elements.forgotBackBtn.addEventListener("click", () => {
            closeForgotModal();
            showAuthModal();
        });
    }

    function setupPasswordToggle(btnId, inputId) {
        const btn = document.getElementById(btnId);
        const input = document.getElementById(inputId);
        if (!btn || !input) return;

        btn.addEventListener("click", (e) => {
            e.preventDefault();
            const isPassword = input.type === "password";
            input.type = isPassword ? "text" : "password";
            btn.setAttribute("aria-label", isPassword ? "Hide password" : "Show password");
            btn.setAttribute("title", isPassword ? "Hide password" : "Show password");
            const eyeOpen = btn.querySelector(".eye-open");
            const eyeClosed = btn.querySelector(".eye-closed");
            if (eyeOpen && eyeClosed) {
                eyeOpen.classList.toggle("hidden", isPassword);
                eyeClosed.classList.toggle("hidden", !isPassword);
            }
        });
    }

    setupPasswordToggle("loginPasswordToggle", "loginPassword");
    setupPasswordToggle("registerPasswordToggle", "registerPassword");

    /* Message input */

    if (elements.messageInput) {

        elements.messageInput.addEventListener(
            "input",
            () => {

                autoResizeTextarea();

                updateMessageCounter();

                updateSendButton();

            }
        );


        elements.messageInput.addEventListener(
            "keydown",
            (event) => {

                if (
                    event.key === "Enter" &&
                    !event.shiftKey
                ) {

                    event.preventDefault();

                    sendMessage();

                }

            }
        );

    }


    /* Send */

    if (elements.sendBtn) {

        elements.sendBtn.addEventListener(
            "click",
            sendMessage
        );

    }

    /* Stop generation */

    if (elements.stopBtn) {

        elements.stopBtn.addEventListener(
            "click",
            stopGeneration
        );

    }


    /* New conversation */

    if (elements.newChatBtn) {

        elements.newChatBtn.addEventListener(
            "click",
            startNewConversation
        );

    }


    /* Refresh conversations */

    if (elements.refreshConversations) {

        elements.refreshConversations.addEventListener(
            "click",
            loadConversations
        );

    }

    /* Conversation search */
    if (elements.conversationSearch) {
        elements.conversationSearch.addEventListener(
            "input",
            () => {
                state.conversationSearch =
                    elements.conversationSearch.value.trim().toLowerCase();

                if (elements.clearConversationSearch) {
                    elements.clearConversationSearch.classList.toggle(
                        "hidden",
                        !state.conversationSearch
                    );
                }

                renderConversationList(state.conversations);
            }
        );
    }

    if (elements.clearConversationSearch) {
        elements.clearConversationSearch.addEventListener(
            "click",
            () => {
                elements.conversationSearch.value = "";
                state.conversationSearch = "";
                elements.clearConversationSearch.classList.add("hidden");
                renderConversationList(state.conversations);
                elements.conversationSearch.focus();
            }
        );
    }


    /* Sidebar toggle (desktop collapse & mobile drawer) */
    const toggleBtn = elements.sidebarToggleBtn || document.getElementById("sidebarToggleBtn");
    if (toggleBtn) {
        toggleBtn.addEventListener("click", (e) => {
            e.preventDefault();
            toggleSidebar();
        });
    }

    const backdrop = elements.sidebarBackdrop || document.getElementById("sidebarBackdrop");
    if (backdrop) {
        backdrop.addEventListener("click", () => {
            closeMobileSidebar();
        });
    }

    window.addEventListener("resize", () => {
        updateSidebarUI();
    });

    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && state.sidebarMobileOpen) {
            closeMobileSidebar();
        }
    });


    /* Close auth modal */

    if (elements.closeAuthModal) {

        elements.closeAuthModal.addEventListener(
            "click",
            closeAuthModal
        );

    }


    /* Login */

    if (elements.loginForm) {

        elements.loginForm.addEventListener(
            "submit",
            handleLogin
        );

    }


    /* Register */

    if (elements.registerForm) {

        elements.registerForm.addEventListener(
            "submit",
            handleRegister
        );

    }


    /* Login/Register switch */

    if (elements.authSwitchBtn) {

        elements.authSwitchBtn.addEventListener(
            "click",
            toggleAuthMode
        );

    }


    /* Profile buttons */

    if (elements.profileBtn) {

        elements.profileBtn.addEventListener(
            "click",
            toggleProfileDropdown
        );

    }


    if (elements.topProfileBtn) {

        elements.topProfileBtn.addEventListener(
            "click",
            toggleProfileDropdown
        );

    }


    /* Logout */

    if (elements.logoutBtn) {

        elements.logoutBtn.addEventListener(
            "click",
            () => logout(true)
        );

    }


    /* Theme */

    if (elements.themeBtn) {

        elements.themeBtn.addEventListener(
            "click",
            toggleTheme
        );

    }


    /* Close conversation menus and profile dropdown */

    document.addEventListener(
        "click",
        () => {
            closeConversationMenus();
        }
    );

    document.addEventListener(
        "click",
        (event) => {

            if (
                elements.profileDropdown &&
                !elements.profileDropdown.contains(
                    event.target
                ) &&
                elements.profileBtn &&
                !elements.profileBtn.contains(
                    event.target
                ) &&
                elements.topProfileBtn &&
                !elements.topProfileBtn.contains(
                    event.target
                )
            ) {

                elements.profileDropdown.classList.add(
                    "hidden"
                );

            }

        }
    );


    /* Rename conversation modal */

    if (elements.renameCancelBtn) {
        elements.renameCancelBtn.addEventListener("click", closeRenameModal);
    }

    if (elements.renameConfirmBtn) {
        elements.renameConfirmBtn.addEventListener("click", handleConfirmRename);
    }

    if (elements.renameInput) {
        elements.renameInput.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                handleConfirmRename();
            } else if (event.key === "Escape") {
                closeRenameModal();
            }
        });
    }

    if (elements.renameModal) {
        elements.renameModal.addEventListener("click", (event) => {
            if (event.target === elements.renameModal) {
                closeRenameModal();
            }
        });
    }

    /* Delete conversation modal */

    if (elements.deleteCancelBtn) {
        elements.deleteCancelBtn.addEventListener("click", closeDeleteModal);
    }

    if (elements.deleteConfirmBtn) {
        elements.deleteConfirmBtn.addEventListener("click", handleConfirmDelete);
    }

    if (elements.deleteModal) {
        elements.deleteModal.addEventListener("click", (event) => {
            if (event.target === elements.deleteModal) {
                closeDeleteModal();
            }
        });
    }

    /* Global Escape key to close modals/menus */

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            closeConversationMenus();
            closeRenameModal();
            closeDeleteModal();
        }
    });

    /* Suggestion cards */

    document
        .querySelectorAll(".suggestion-card")
        .forEach((button) => {

            button.addEventListener(
                "click",
                () => {

                    const message =
                        button.dataset.message;

                    if (!elements.messageInput) {
                        return;
                    }

                    elements.messageInput.value =
                        message;

                    updateSendButton();

                    sendMessage();

                }
            );

        });

}


/* =========================================================
   API HELPER
   ========================================================= */

async function apiRequest(
    endpoint,
    options = {}
) {

    const headers = {
        "Content-Type": "application/json",
        ...(options.headers || {})
    };

    const isAuthEndpoint =
        endpoint.startsWith("/auth/login") ||
        endpoint.startsWith("/auth/register");

    if (state.token && !isAuthEndpoint) {
        headers.Authorization = `Bearer ${state.token}`;
    }

    let response;
    try {
        response = await fetch(
            `${API_BASE_URL}${endpoint}`,
            {
                ...options,
                headers
            }
        );
    } catch (netErr) {
        throw new Error(
            "Unable to connect to the server. Please check your connection."
        );
    }

    let data = {};
    try {
        data = await response.json();
    } catch {
        data = {};
    }

    if (!response.ok) {
        if (response.status === 401) {
            if (isAuthEndpoint) {
                throw new Error(
                    (typeof data?.detail === "string" && data.detail) ||
                    data?.message ||
                    "Incorrect email or password."
                );
            }

            logout(false);

            throw new Error(
                "Your session has expired. Please sign in again."
            );
        }

        if (response.status === 403) {
            throw new Error(
                (typeof data?.detail === "string" && data.detail) ||
                data?.message ||
                "Access denied: You do not have permission to perform this action."
            );
        }

        if (response.status === 422) {
            let msg = "Invalid input format. Please check your data.";
            if (Array.isArray(data?.detail) && data.detail.length > 0) {
                msg = data.detail.map((d) => d.msg || "invalid field").join("; ");
            } else if (typeof data?.detail === "string") {
                msg = data.detail;
            }
            throw new Error(msg);
        }

        if (response.status === 503) {
            throw new Error(
                (typeof data?.detail === "string" && data.detail) ||
                "Database service is temporarily unavailable. Please try again later."
            );
        }

        throw new Error(
            (typeof data?.detail === "string" && data.detail) ||
            data?.message ||
            `Request failed (HTTP ${response.status}).`
        );
    }

    return data;
}


/* =========================================================
   AUTH UI
   ========================================================= */

function showRoleScreen() {
    if (elements.entryScreen) {
        elements.entryScreen.classList.remove("hidden");
    }
}

function hideEntryScreen() {
    if (elements.entryScreen) {
        elements.entryScreen.classList.add("hidden");
    }
}

function showForgotModal() {
    if (elements.forgotModal) {
        elements.forgotModal.classList.remove("hidden");
    }
}

function closeForgotModal() {
    if (elements.forgotModal) {
        elements.forgotModal.classList.add("hidden");
    }
}

function showAuthModal() {

    if (!elements.authModal) {
        return;
    }

    elements.authModal.classList.remove(
        "hidden"
    );

}


function closeAuthModal() {

    if (!elements.authModal) {
        return;
    }

    elements.authModal.classList.add(
        "hidden"
    );

    if (!state.token) {
        showRoleScreen();
    }

}


function toggleAuthMode() {

    state.authMode =
        state.authMode === "login"
            ? "register"
            : "login";


    if (elements.authError) {

        elements.authError.classList.add(
            "hidden"
        );

    }


    if (state.authMode === "login") {

        elements.loginForm.classList.remove(
            "hidden"
        );

        elements.registerForm.classList.add(
            "hidden"
        );


        elements.authTitle.textContent =
            "Welcome back";

        elements.authSubtitle.textContent =
            "Sign in to continue to SupportAI.";

        elements.authSwitchText.textContent =
            "Don't have an account?";

        elements.authSwitchBtn.textContent =
            "Create one";

    } else {

        elements.loginForm.classList.add(
            "hidden"
        );

        elements.registerForm.classList.remove(
            "hidden"
        );


        elements.authTitle.textContent =
            "Create your account";

        elements.authSubtitle.textContent =
            "Start using AI-powered customer support.";

        elements.authSwitchText.textContent =
            "Already have an account?";

        elements.authSwitchBtn.textContent =
            "Sign in";

    }

}


/* =========================================================
   LOGIN
   ========================================================= */

async function handleLogin(event) {

    event.preventDefault();


    const email =
        elements.loginEmail.value.trim().toLowerCase();

    const password =
        elements.loginPassword.value;


    if (!email || !password) {

        showAuthError(
            "Please enter your email and password."
        );

        return;

    }


    setAuthLoading(
        elements.loginForm,
        true
    );


    try {

        const data =
            await apiRequest(
                "/auth/login",
                {
                    method: "POST",

                    body: JSON.stringify({
                        email,
                        password
                    })
                }
            );


        /*
         * Role-based separation: If an admin logs in, save admin_token and redirect to /admin/
         */
        if (data.role === "admin") {
            if (typeof localStorage !== "undefined") {
                localStorage.setItem("admin_token", data.access_token);
                localStorage.removeItem("supportai_token");
                localStorage.removeItem("supportai_user");
            }
            state.token = null;
            state.user = null;
            closeAuthModal();
            showToast("Admin account verified. Redirecting to Admin Control Center...");
            window.location.replace("../admin/");
            return;
        }

        /*
         * Save the fresh customer JWT.
         */
        state.token = data.access_token;
        if (typeof localStorage !== "undefined") {
            localStorage.setItem("supportai_token", state.token);
        }

        /*
         * Validate the new token and load the current customer.
         */
        await loadCurrentUser();

        closeAuthModal();
        hideEntryScreen();

        showToast("Welcome back!");

        /*
         * Load previous conversations.
         */
        await loadConversations();


        elements.messageInput?.focus();

    } catch (error) {

        showAuthError(
            error.message
        );

    } finally {

        setAuthLoading(
            elements.loginForm,
            false
        );

    }

}


/* =========================================================
   REGISTER
   ========================================================= */

async function handleRegister(event) {

    event.preventDefault();


    const name =
        elements.registerName.value.trim();

    const email =
        elements.registerEmail.value.trim().toLowerCase();

    const password =
        elements.registerPassword.value;


    if (!name || !email || !password) {

        showAuthError(
            "Please fill in all fields."
        );

        return;

    }


    if (password.length < 10) {

        showAuthError(
            "Password must contain at least 10 characters."
        );

        return;

    }


    setAuthLoading(
        elements.registerForm,
        true
    );


    try {

        const data =
            await apiRequest(
                "/auth/register",
                {
                    method: "POST",

                    body: JSON.stringify({

                        name,

                        email,

                        password,

                        role: "customer"

                    })
                }
            );


        toggleAuthMode();
        elements.loginEmail.value = email;
        elements.loginPassword.focus();
        showAuthError(data.detail || "If this email can be registered, you can now log in.");

    } catch (error) {

        showAuthError(
            error.message
        );

    } finally {

        setAuthLoading(
            elements.registerForm,
            false
        );

    }

}


/* =========================================================
   CURRENT USER
   ========================================================= */

async function loadCurrentUser() {
    const user = await apiRequest("/auth/me");
    if (user.role === "admin") {
        if (state.token && typeof localStorage !== "undefined") {
            localStorage.setItem("admin_token", state.token);
            localStorage.removeItem("supportai_token");
            localStorage.removeItem("supportai_user");
        }
        state.token = null;
        state.user = null;
        window.location.replace("../admin/");
        return user;
    }

    state.user = user;
    if (typeof localStorage !== "undefined") {
        localStorage.setItem("supportai_user", JSON.stringify(user));
    }
    updateUserUI();
    return user;
}


/* =========================================================
   IMPORTANT:
   VALIDATE EXISTING SESSION ON PAGE LOAD
   ========================================================= */

async function initializeAuthenticatedApp() {
    const tokenToVerify = state.token || (typeof localStorage !== "undefined" ? localStorage.getItem("admin_token") : null);

    if (!tokenToVerify) {
        showRoleScreen();
        return;
    }

    try {
        /*
         * Step 1: Validate session with /auth/me
         */
        const user = await apiRequest("/auth/me", {
            headers: {
                Authorization: `Bearer ${tokenToVerify}`
            }
        });

        /*
         * Step 2: Role-based separation
         * If the authenticated account is an admin, redirect them immediately to /admin/
         */
        if (user.role === "admin") {
            if (typeof localStorage !== "undefined") {
                localStorage.setItem("admin_token", tokenToVerify);
                localStorage.removeItem("supportai_token");
                localStorage.removeItem("supportai_user");
            }
            state.token = null;
            state.user = null;
            window.location.replace("../admin/");
            return;
        }

        if (user.role === "customer") {
            state.token = tokenToVerify;
            state.user = user;
            if (typeof localStorage !== "undefined") {
                localStorage.setItem("supportai_token", state.token);
                localStorage.setItem("supportai_user", JSON.stringify(user));
            }

            updateUserUI();
            hideEntryScreen();
            closeAuthModal();
            closeForgotModal();

            /*
             * Step 4: Load customer's previous conversations
             */
            await loadConversations();

            if (state.conversationId) {
                await loadConversation(state.conversationId);
            }
            return;
        }

        /*
         * Unknown role fallback
         */
        logout(false);
        showRoleScreen();

    } catch (error) {
        /*
         * Old/expired token. Clean everything and show login.
         */
        console.warn("Existing session is no longer valid:", error);
        logout(false);
        showRoleScreen();
    }
}


/* =========================================================
   LOGOUT
   ========================================================= */

function logout(
    showMessage = true
) {

    state.token = null;

    state.user = null;

    state.conversationId = null;


    localStorage.removeItem(
        "supportai_token"
    );

    localStorage.removeItem(
        "supportai_user"
    );

    localStorage.removeItem(
        "supportai_conversation_id"
    );


    if (elements.messagesContainer) {

        elements.messagesContainer.innerHTML =
            "";

    }


    if (elements.welcomeScreen) {

        elements.welcomeScreen.classList.remove(
            "hidden"
        );

    }


    if (elements.conversationList) {

        elements.conversationList.innerHTML = `

            <div class="empty-conversations">

                <span>◌</span>

                <p>No conversations yet</p>

            </div>

        `;

    }


    updateUserUI();

    showAuthModal();


    if (showMessage) {

        showToast(
            "You have been signed out."
        );

    }

}


/* =========================================================
   USER UI
   ========================================================= */

function updateUserUI() {

    if (!state.user) {

        elements.sidebarName.textContent =
            "Guest";

        elements.sidebarEmail.textContent =
            "Not signed in";

        elements.topUserName.textContent =
            "Guest";

        elements.dropdownName.textContent =
            "Guest";

        elements.dropdownEmail.textContent =
            "-";

        setAvatarLetter("G");

        return;

    }


    const name =
        state.user.name ||
        state.user.email ||
        "User";

    const email =
        state.user.email ||
        "";


    elements.sidebarName.textContent =
        name;

    elements.sidebarEmail.textContent =
        email;

    elements.topUserName.textContent =
        name;

    elements.dropdownName.textContent =
        name;

    elements.dropdownEmail.textContent =
        email;


    setAvatarLetter(
        name.charAt(0).toUpperCase()
    );

}


function setAvatarLetter(letter) {

    if (elements.sidebarAvatar) {

        elements.sidebarAvatar.textContent =
            letter;

    }

    if (elements.topAvatar) {

        elements.topAvatar.textContent =
            letter;

    }

    if (elements.dropdownAvatar) {

        elements.dropdownAvatar.textContent =
            letter;

    }

}


/* =========================================================
   CHAT
   ========================================================= */

async function sendMessage(retryRequestId = null) {

    if (state.isSending) {

        return;

    }


    const message =
        elements.messageInput.value.trim();


    if (!message) {

        return;

    }


    if (!state.token) {

        showAuthModal();

        return;

    }


    state.isSending = true;
    state.abortController = new AbortController();
    setGeneratingUI(true);


    /*
     * Show user's message immediately.
     */

    const requestId = retryRequestId || crypto.randomUUID();

    addMessage(
        "user",
        message,
        new Date(),
        false,
        requestId
    );


    elements.messageInput.value = "";

    autoResizeTextarea();

    updateSendButton();


    elements.welcomeScreen.classList.add(
        "hidden"
    );


    showThinking();


    try {

        const payload = {

            message,
            request_id: requestId

        };


        /*
         * Continue existing conversation
         * when conversation ID exists.
         */

        if (state.conversationId) {

            payload.conversation_id =
                state.conversationId;

        }


        /*
         * Send to FastAPI.
         *
         * FastAPI then calls the existing
         * Google ADK customer support workflow.
         */

        const data =
            await apiRequest(
                "/chat/message",
                {
                    method: "POST",
                    body:
                        JSON.stringify(
                            payload
                        ),
                    signal: state.abortController.signal
                }
            );


        /*
         * Save conversation ID returned
         * by the backend.
         */

        state.conversationId =
            data.conversation_id;


        localStorage.setItem(
            "supportai_conversation_id",
            state.conversationId
        );


        /*
         * Display AI response.
         */

        if (data.error) {
            addMessage(
                "assistant",
                data.response,
                new Date(),
                true
            );
        } else {
            addMessage(
                "assistant",
                data.response
            );
        }


        updateConversationTitle(
            message
        );


        /*
         * Refresh sidebar.
         */

        await loadConversations();

    } catch (error) {

        if (
            error.name === "AbortError" ||
            (error.message && error.message.toLowerCase().includes("aborted"))
        ) {
            addMessage(
                "assistant",
                "⚠️ *Response generation was stopped.*"
            );
            showToast("Generation stopped.");
        } else if (
            error.message && (
                error.message.includes("temporarily receiving too many requests") ||
                error.message.includes("busy") ||
                error.message.includes("429") ||
                error.message.includes("RESOURCE_EXHAUSTED")
            )
        ) {
            addMessage(
                "assistant",
                `⚠️ **Service Notice**\n\n${error.message}`
            );
        } else {
            addMessage(
                "assistant",
                `⚠️ **Something went wrong.**\n\n${error.message}`
            );
        }

    } finally {

        hideThinking();

        state.abortController = null;
        state.isSending = false;

        setGeneratingUI(false);
        updateSendButton();

        elements.messageInput?.focus();

    }

}


/* =========================================================
   ADD MESSAGE
   ========================================================= */

function createCopyButton(text) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "message-action-btn";
    button.title = "Copy";
    button.setAttribute("aria-label", "Copy");
    button.textContent = "📋";
    button.addEventListener("click", async () => {
        try {
            await navigator.clipboard.writeText(text || "");
            showToast("Response copied.");
        } catch {
            showToast("Unable to copy response.");
        }
    });
    return button;
}

function addMessage(
    role,
    text,
    timestamp = new Date(),
    isError = false,
    requestId = null
) {

    const row =
        document.createElement("div");


    row.className =
        `message-row ${role}`;


    const avatar =
        document.createElement("div");


    avatar.className =
        `message-avatar ${
            role === "assistant"
                ? "ai-avatar"
                : "user-avatar"
        }`;


    avatar.textContent =
        role === "assistant"
            ? "✦"
            : getUserInitial();


    const content =
        document.createElement("div");


    content.className =
        "message-content";


    const label =
        document.createElement("div");


    label.className =
        "message-label";


    label.textContent =
        role === "assistant"
            ? "SupportAI"
            : "You";


    const bubble =
        document.createElement("div");


    bubble.className =
        "message-bubble";


    if (role === "assistant") {

        bubble.innerHTML =
            formatAssistantMessage(text);

    } else {

        bubble.textContent =
            text;

    }


    const time =
        document.createElement("div");

    time.className =
        "message-time";

    time.textContent =
        formatTime(timestamp);

    content.appendChild(label);
    content.appendChild(bubble);

    if (role === "assistant" && !isError) {

        const actions =
            document.createElement("div");

        actions.className =
            "message-actions";

        const copyButton = createCopyButton(text);

        const likeButton =
            document.createElement("button");

        likeButton.type = "button";
        likeButton.className = "message-action-btn";
        likeButton.title = "Helpful";
        likeButton.setAttribute("aria-label", "Helpful");
        likeButton.textContent = "👍";

        likeButton.addEventListener(
            "click",
            async () => {
                const wasSelected = likeButton.classList.contains("selected");
                if (wasSelected) return;
                likeButton.classList.add("selected");
                dislikeButton.classList.remove("selected");
                if (state.conversationId) {
                    try {
                        await apiRequest("/chat/feedback", {
                            method: "POST",
                            body: JSON.stringify({
                                conversation_id: state.conversationId,
                                rating: "like",
                            }),
                        });
                        showToast("Thanks for your feedback.");
                    } catch {
                        likeButton.classList.remove("selected");
                        showToast("Failed to save feedback. Please try again.");
                    }
                }
            }
        );

        const dislikeButton =
            document.createElement("button");

        dislikeButton.type = "button";
        dislikeButton.className = "message-action-btn";
        dislikeButton.title = "Not helpful";
        dislikeButton.setAttribute("aria-label", "Not helpful");
        dislikeButton.textContent = "👎";

        dislikeButton.addEventListener(
            "click",
            async () => {
                const wasSelected = dislikeButton.classList.contains("selected");
                if (wasSelected) return;
                dislikeButton.classList.add("selected");
                likeButton.classList.remove("selected");
                if (state.conversationId) {
                    try {
                        await apiRequest("/chat/feedback", {
                            method: "POST",
                            body: JSON.stringify({
                                conversation_id: state.conversationId,
                                rating: "dislike",
                            }),
                        });
                        showToast("Thanks for your feedback.");
                    } catch {
                        dislikeButton.classList.remove("selected");
                        showToast("Failed to save feedback. Please try again.");
                    }
                }
            }
        );

        actions.appendChild(copyButton);
        actions.appendChild(likeButton);
        actions.appendChild(dislikeButton);

        content.appendChild(actions);

    } else if (role === "assistant" && isError) {

        const actions =
            document.createElement("div");

        actions.className =
            "message-actions";

        const copyButton = createCopyButton(text);

        actions.appendChild(copyButton);
        content.appendChild(actions);

    } else if (role === "user") {

        const userActions =
            document.createElement("div");

        userActions.className =
            "message-actions user-actions";

        const copyBtn =
            document.createElement("button");

        copyBtn.type = "button";
        copyBtn.className = "message-action-btn";
        copyBtn.title = "Copy";
        copyBtn.setAttribute("aria-label", "Copy");
        copyBtn.textContent = "📋";

        copyBtn.addEventListener(
            "click",
            async () => {
                try {
                    await navigator.clipboard.writeText(
                        text || ""
                    );
                    showToast("Message copied.");
                } catch {
                    showToast("Unable to copy message.");
                }
            }
        );

        const editBtn =
            document.createElement("button");

        editBtn.type = "button";
        editBtn.className = "message-action-btn";
        editBtn.title = "Edit";
        editBtn.setAttribute("aria-label", "Edit");
        editBtn.textContent = "✏️";

        editBtn.addEventListener(
            "click",
            () => {
                if (elements.messageInput) {
                    elements.messageInput.value = text || "";
                    autoResizeTextarea();
                    updateSendButton();
                    elements.messageInput.focus();
                    showToast("Message loaded into input.");
                }
            }
        );

        const resendBtn =
            document.createElement("button");

        resendBtn.type = "button";
        resendBtn.className = "message-action-btn";
        resendBtn.title = "Retry";
        resendBtn.setAttribute("aria-label", "Retry");
        resendBtn.textContent = "↻";

        resendBtn.addEventListener(
            "click",
            () => {
                if (state.isSending) {
                    showToast("Please wait for the current response to finish.");
                    return;
                }
                if (elements.messageInput) {
                    elements.messageInput.value = text || "";
                    updateSendButton();
                    sendMessage(requestId);
                }
            }
        );

        userActions.appendChild(copyBtn);
        userActions.appendChild(editBtn);
        userActions.appendChild(resendBtn);

        content.appendChild(userActions);

    }

    content.appendChild(time);


    if (role === "assistant") {

        row.appendChild(avatar);

        row.appendChild(content);

    } else {

        row.appendChild(content);

        row.appendChild(avatar);

    }


    elements.messagesContainer.appendChild(
        row
    );


    scrollChatToBottom();

}


/* =========================================================
   LOAD CONVERSATIONS
   ========================================================= */

async function loadConversations() {

    if (!state.token) {

        return;

    }


    try {

        const conversations =
            await apiRequest(
                "/chat/conversations"
            );


        state.conversations = conversations || [];

        renderConversationList(
            state.conversations
        );

    } catch (error) {

        console.error(
            "Conversation loading failed:",
            error
        );

    }

}


/* =========================================================
   RENDER CONVERSATIONS
   ========================================================= */

function renderConversationList(
    conversations
) {

    const allConversations = Array.isArray(conversations)
        ? conversations
        : [];

    const query = state.conversationSearch || "";

    const filtered = query
        ? allConversations.filter((conversation) => {
            const title =
                (conversation.title || "").toLowerCase();

            const fallback =
                `conversation ${String(conversation.id || "").slice(-6)}`.toLowerCase();

            return title.includes(query) || fallback.includes(query);
        })
        : allConversations;

    if (!filtered.length) {

        elements.conversationList.innerHTML = `

            <div class="empty-conversations">

                <span>${query ? "⌕" : "◌"}</span>

                <p>${query ? "No matching conversations" : "No conversations yet"}</p>

                ${
                    query
                        ? `<small>Try another search term.</small>`
                        : ""
                }

            </div>

        `;

        return;
    }

    elements.conversationList.innerHTML = "";

    filtered.forEach(
        (conversation) => {

            const item =
                document.createElement("div");

            item.className = "conversation-item-wrap";

            const button =
                document.createElement("button");

            button.type = "button";
            button.className = "conversation-item";

            if (
                conversation.id ===
                state.conversationId
            ) {
                button.classList.add("active");
            }

            const title =
                document.createElement("div");

            title.className =
                "conversation-item-title";

            title.textContent =
                conversation.title ||
                `Conversation ${String(conversation.id).slice(-6)}`;

            const meta =
                document.createElement("div");

            meta.className =
                "conversation-item-meta";

            meta.textContent =
                `${conversation.message_count || 0} ${
                    conversation.message_count === 1
                        ? "message"
                        : "messages"
                }`;

            button.appendChild(title);
            button.appendChild(meta);

            button.addEventListener(
                "click",
                () => {
                    loadConversation(conversation.id);
                }
            );

            const menuButton =
                document.createElement("button");

            menuButton.type = "button";
            menuButton.className = "conversation-menu-btn";
            menuButton.title = "Conversation options";
            menuButton.setAttribute(
                "aria-label",
                "Conversation options"
            );
            menuButton.textContent = "⋮";

            menuButton.addEventListener(
                "click",
                (event) => {
                    event.stopPropagation();
                    openConversationMenu(
                        menuButton,
                        conversation
                    );
                }
            );

            item.appendChild(button);
            item.appendChild(menuButton);

            elements.conversationList.appendChild(item);

        }
    );

}


function closeConversationMenus() {
    document
        .querySelectorAll(".conversation-action-menu")
        .forEach((menu) => menu.remove());
}


function openConversationMenu(anchor, conversation) {

    closeConversationMenus();

    const menu =
        document.createElement("div");

    menu.className =
        "conversation-action-menu";

    const renameButton =
        document.createElement("button");

    renameButton.type = "button";
    renameButton.innerHTML = "✏️ <span>Rename</span>";

    renameButton.addEventListener(
        "click",
        (event) => {
            event.stopPropagation();
            closeConversationMenus();
            openRenameModal(conversation);
        }
    );

    const deleteButton =
        document.createElement("button");

    deleteButton.type = "button";
    deleteButton.className = "danger";
    deleteButton.innerHTML = "🗑️ <span>Delete</span>";

    deleteButton.addEventListener(
        "click",
        (event) => {
            event.stopPropagation();
            closeConversationMenus();
            openDeleteModal(conversation);
        }
    );

    menu.appendChild(renameButton);
    menu.appendChild(deleteButton);

    document.body.appendChild(menu);

    const rect =
        anchor.getBoundingClientRect();

    const menuWidth = 150;

    menu.style.position = "fixed";
    menu.style.left =
        `${Math.max(8, Math.min(
            window.innerWidth - menuWidth - 8,
            rect.right - menuWidth
        ))}px`;
    menu.style.top =
        `${Math.min(
            window.innerHeight - 100,
            rect.bottom + 6
        )}px`;

    requestAnimationFrame(() => {
        document.addEventListener(
            "click",
            closeConversationMenus,
            { once: true }
        );
    });
}


/* =========================================================
   RENAME CONVERSATION MODAL FLOW
   ========================================================= */

function openRenameModal(conversation) {
    state._pendingRenameConversation = conversation;
    const currentTitle =
        conversation.title ||
        `Conversation ${String(conversation.id).slice(-6)}`;

    if (elements.renameInput) {
        elements.renameInput.value = currentTitle;
    }

    if (elements.renameModal) {
        elements.renameModal.classList.remove("hidden");
        setTimeout(() => {
            elements.renameInput?.focus();
            elements.renameInput?.select();
        }, 50);
    }
}

function closeRenameModal() {
    state._pendingRenameConversation = null;
    if (elements.renameModal) {
        elements.renameModal.classList.add("hidden");
    }
}

async function handleConfirmRename() {
    const conversation = state._pendingRenameConversation;
    if (!conversation) {
        return;
    }

    const title = (elements.renameInput?.value || "").trim();

    if (!title) {
        showToast("Conversation name cannot be empty.");
        return;
    }

    if (title.length > 80) {
        showToast("Conversation name must be 80 characters or less.");
        return;
    }

    closeRenameModal();

    try {
        await apiRequest(
            `/chat/conversations/${conversation.id}`,
            {
                method: "PATCH",
                body: JSON.stringify({ title })
            }
        );

        showToast("Conversation renamed.");
        await loadConversations();

        if (state.conversationId === conversation.id) {
            elements.conversationTitle.textContent = title;
        }
    } catch (error) {
        showToast(
            error.message ||
            "Unable to rename conversation."
        );
    }
}


/* =========================================================
   DELETE CONVERSATION MODAL FLOW
   ========================================================= */

function openDeleteModal(conversation) {
    state._pendingDeleteConversation = conversation;
    const title =
        conversation.title ||
        `Conversation ${String(conversation.id).slice(-6)}`;

    if (elements.deleteModalDesc) {
        elements.deleteModalDesc.textContent =
            `Are you sure you want to delete "${title}"? This conversation and all its messages will be permanently removed.`;
    }

    if (elements.deleteModal) {
        elements.deleteModal.classList.remove("hidden");
    }
}

function closeDeleteModal() {
    state._pendingDeleteConversation = null;
    if (elements.deleteModal) {
        elements.deleteModal.classList.add("hidden");
    }
}

async function handleConfirmDelete() {
    const conversation = state._pendingDeleteConversation;
    if (!conversation) {
        return;
    }

    closeDeleteModal();

    try {
        await apiRequest(
            `/chat/conversations/${conversation.id}`,
            {
                method: "DELETE"
            }
        );

        if (state.conversationId === conversation.id) {
            state.conversationId = null;

            localStorage.removeItem(
                "supportai_conversation_id"
            );

            if (elements.messagesContainer) {
                elements.messagesContainer.innerHTML = "";
            }

            if (elements.welcomeScreen) {
                elements.welcomeScreen.classList.remove(
                    "hidden"
                );
            }

            if (elements.conversationTitle) {
                elements.conversationTitle.textContent =
                    "New conversation";
            }
        }

        showToast("Conversation deleted.");
        await loadConversations();

    } catch (error) {
        showToast(
            error.message ||
            "Unable to delete conversation."
        );
    }
}


/* =========================================================
   LOAD ONE CONVERSATION
   ========================================================= */

async function loadConversation(
    conversationId
) {

    closeMobileSidebar();

    if (!state.token) {

        return;

    }


    try {

        const conversation =
            await apiRequest(
                `/chat/conversations/${conversationId}`
            );


        state.conversationId =
            conversation.id;


        localStorage.setItem(
            "supportai_conversation_id",
            state.conversationId
        );


        elements.messagesContainer.innerHTML =
            "";


        if (
            conversation.messages &&
            conversation.messages.length > 0
        ) {

            elements.welcomeScreen.classList.add(
                "hidden"
            );


            conversation.messages.forEach(
                (message) => {

                    addMessage(
                        message.role,
                        message.content,

                        message.timestamp
                            ? new Date(
                                message.timestamp
                            )
                            : new Date()
                    );

                }
            );

        } else {

            elements.welcomeScreen.classList.remove(
                "hidden"
            );

        }


        updateConversationTitle(
            "Conversation"
        );


        renderActiveConversation();

        closeMobileSidebar();

    } catch (error) {

        showToast(
            error.message
        );

    }

}


/* =========================================================
   ACTIVE CONVERSATION
   ========================================================= */

function renderActiveConversation() {

    document
        .querySelectorAll(
            ".conversation-item"
        )
        .forEach(
            (item) => {

                item.classList.remove(
                    "active"
                );

            }
        );


    /*
     * Re-render the sidebar so the current
     * conversation receives the active style.
     */

    loadConversations();

}


/* =========================================================
   NEW CONVERSATION
   ========================================================= */

function startNewConversation() {

    closeMobileSidebar();

    state.conversationId = null;

    localStorage.removeItem(
        "supportai_conversation_id"
    );


    elements.messagesContainer.innerHTML =
        "";


    elements.welcomeScreen.classList.remove(
        "hidden"
    );


    elements.conversationTitle.textContent =
        "New conversation";


    renderConversationListFromState();

    closeMobileSidebar();

    elements.messageInput.focus();

}


/* =========================================================
   RESET ACTIVE SIDEBAR STATE
   ========================================================= */

function renderConversationListFromState() {

    document
        .querySelectorAll(
            ".conversation-item"
        )
        .forEach(
            (item) => {

                item.classList.remove(
                    "active"
                );

            }
        );

}


/* =========================================================
   THINKING STATE
   ========================================================= */

function showThinking() {

    if (!elements.thinkingIndicator) {
        return;
    }

    elements.thinkingIndicator.classList.remove(
        "hidden"
    );


    scrollChatToBottom();

}


function hideThinking() {

    if (!elements.thinkingIndicator) {
        return;
    }

    elements.thinkingIndicator.classList.add(
        "hidden"
    );

}


/* =========================================================
   MESSAGE COUNTER
   ========================================================= */

function updateMessageCounter() {

    if (!elements.messageCounter || !elements.messageInput) {
        return;
    }

    const length =
        elements.messageInput.value.length;

    elements.messageCounter.textContent =
        `${length} / 4000`;

    elements.messageCounter.classList.toggle(
        "near-limit",
        length >= 3600
    );
}


/* =========================================================
   SEND BUTTON
   ========================================================= */

function updateSendButton() {

    if (!elements.sendBtn) {
        return;
    }


    const hasText =
        elements.messageInput &&
        elements.messageInput.value
            .trim()
            .length > 0;


    elements.sendBtn.disabled =
        !hasText ||
        state.isSending;

}


/* =========================================================
   STOP GENERATION CONTROLS
   ========================================================= */

function setGeneratingUI(isGenerating) {
    if (elements.sendBtnWrap && elements.stopBtnWrap) {
        if (isGenerating) {
            elements.sendBtnWrap.classList.add("hidden");
            elements.stopBtnWrap.classList.remove("hidden");
        } else {
            elements.stopBtnWrap.classList.add("hidden");
            elements.sendBtnWrap.classList.remove("hidden");
        }
    }
}

function stopGeneration() {
    if (state.abortController) {
        state.abortController.abort();
        state.abortController = null;
    }
}


/* =========================================================
   TEXTAREA
   ========================================================= */

function autoResizeTextarea() {

    const textarea =
        elements.messageInput;


    if (!textarea) {
        return;
    }


    textarea.style.height =
        "auto";


    textarea.style.height =
        `${Math.min(
            textarea.scrollHeight,
            150
        )}px`;

}


/* =========================================================
   SCROLL CHAT
   ========================================================= */

function scrollChatToBottom() {

    const chat =
        document.querySelector(
            ".chat-area"
        );


    if (!chat) {
        return;
    }


    requestAnimationFrame(
        () => {

            chat.scrollTo({

                top:
                    chat.scrollHeight,

                behavior:
                    "smooth"

            });

        }
    );

}


/* =========================================================
   FORMAT TIME
   ========================================================= */

function formatTime(date) {

    const d =
        date instanceof Date
            ? date
            : new Date(date);


    if (
        Number.isNaN(
            d.getTime()
        )
    ) {

        return "";

    }


    return d.toLocaleTimeString(
        [],
        {
            hour: "2-digit",
            minute: "2-digit"
        }
    );

}


/* =========================================================
   USER INITIAL
   ========================================================= */

function getUserInitial() {

    if (
        state.user &&
        state.user.name
    ) {

        return state.user.name
            .charAt(0)
            .toUpperCase();

    }


    if (
        state.user &&
        state.user.email
    ) {

        return state.user.email
            .charAt(0)
            .toUpperCase();

    }


    return "U";

}


/* =========================================================
   CONVERSATION TITLE
   ========================================================= */

function updateConversationTitle(
    text
) {

    if (!text) {
        return;
    }


    const clean =
        text
            .replace(/\s+/g, " ")
            .trim();


    elements.conversationTitle.textContent =
        clean.length > 55
            ? `${clean.substring(0, 55)}...`
            : clean;

}


/* =========================================================
   SIMPLE MARKDOWN FORMATTER
   ========================================================= */

function formatAssistantMessage(
    text
) {

    let safe =
        escapeHtml(
            text || ""
        );


    /*
     * Bold
     */

    safe =
        safe.replace(
            /\*\*(.*?)\*\*/g,
            "<strong>$1</strong>"
        );

    /*
     * Italic
     */

    safe =
        safe.replace(
            /\*([^*]+)\*/g,
            "<em>$1</em>"
        ).replace(
            /_([^_]+)_/g,
            "<em>$1</em>"
        );


    /*
     * Inline code
     */

    safe =
        safe.replace(
            /`([^`]+)`/g,
            "<code>$1</code>"
        );


    const lines =
        safe.split("\n");


    let html = "";

    let inList = false;


    lines.forEach(
        (line) => {

            const trimmed =
                line.trim();


            /*
             * Bullet list
             */

            if (
                trimmed.startsWith("- ")
            ) {

                if (!inList) {

                    html += "<ul>";

                    inList = true;

                }


                html +=
                    `<li>${trimmed.substring(2)}</li>`;

                return;

            }


            if (inList) {

                html += "</ul>";

                inList = false;

            }


            /*
             * Empty line
             */

            if (!trimmed) {

                html += "<br>";

                return;

            }


            /*
             * Normal paragraph
             */

            html +=
                `<p>${trimmed}</p>`;

        }
    );


    if (inList) {

        html += "</ul>";

    }


    return html;

}


/* =========================================================
   HTML ESCAPING
   ========================================================= */

function escapeHtml(
    value
) {

    return value

        .replace(
            /&/g,
            "&amp;"
        )

        .replace(
            /</g,
            "&lt;"
        )

        .replace(
            />/g,
            "&gt;"
        )

        .replace(
            /"/g,
            "&quot;"
        )

        .replace(
            /'/g,
            "&#039;"
        );

}


/* =========================================================
   AUTH ERROR
   ========================================================= */

function showAuthError(
    message
) {

    elements.authError.textContent =
        message;


    elements.authError.classList.remove(
        "hidden"
    );

}


/* =========================================================
   AUTH LOADING
   ========================================================= */

function setAuthLoading(
    form,
    loading
) {

    if (!form) {
        return;
    }


    const button =
        form.querySelector(
            "button[type='submit']"
        );


    if (!button) {
        return;
    }


    if (loading) {

        button.dataset.originalText =
            button.textContent;


        button.textContent =
            "Please wait...";


        button.disabled = true;

    } else {

        button.textContent =
            button.dataset.originalText ||
            "Submit";


        button.disabled = false;

    }

}


/* =========================================================
   PROFILE
   ========================================================= */

function toggleProfileDropdown() {

    if (!elements.profileDropdown) {
        return;
    }


    elements.profileDropdown.classList.toggle(
        "hidden"
    );

}



/* =========================================================
   THEME
   ========================================================= */

function setupTheme() {

    const savedTheme =
        localStorage.getItem(
            "supportai_theme"
        );


    if (savedTheme === "light") {

        document.body.classList.add(
            "light-theme"
        );

    }

}


function toggleTheme() {

    document.body.classList.toggle(
        "light-theme"
    );


    const isLight =
        document.body.classList.contains(
            "light-theme"
        );


    localStorage.setItem(
        "supportai_theme",
        isLight
            ? "light"
            : "dark"
    );

}


/* =========================================================
   TOAST
   ========================================================= */

let toastTimer = null;


function showToast(
    message
) {

    if (!elements.toast) {
        return;
    }


    elements.toast.textContent =
        message;


    elements.toast.classList.add(
        "show"
    );


    clearTimeout(
        toastTimer
    );


    toastTimer =
        setTimeout(
            () => {

                elements.toast.classList.remove(
                    "show"
                );

            },
            2500
        );

}

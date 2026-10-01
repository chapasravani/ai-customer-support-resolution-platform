/**
 * SupportAI Shared Frontend Configuration (L5)
 * 
 * Provides unified API origin resolution and runtime configuration
 * across customer and admin frontend applications.
 */

const SUPPORTAI_CONFIG = (() => {
    const hostname = typeof window !== "undefined" && window.location ? window.location.hostname : "localhost";
    const protocol = typeof window !== "undefined" && window.location ? window.location.protocol : "http:";

    const isLocalhost = hostname === "localhost" || hostname === "127.0.0.1";

    const apiBaseUrl = isLocalhost
        ? "http://localhost:8000"
        : `${protocol}//${hostname}:8000`;

    return {
        API_URL: (typeof window !== "undefined" && window.__SUPPORTAI_API_URL__) || apiBaseUrl,
        IS_LOCAL: isLocalhost,
    };
})();

if (typeof window !== "undefined") {
    window.SUPPORTAI_CONFIG = SUPPORTAI_CONFIG;
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = SUPPORTAI_CONFIG;
}

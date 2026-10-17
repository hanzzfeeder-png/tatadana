// TataDana Global Frontend Utilities

function formatIDR(amount) {
    if (isNaN(amount) || amount === null || amount === undefined) return "Rp 0";
    return new Intl.NumberFormat("id-ID", {
        style: "currency",
        currency: "IDR",
        minimumFractionDigits: 0,
        maximumFractionDigits: 0
    }).format(amount).replace("Rp", "Rp ");
}

function showToast(message, type = "success") {
    let container = document.getElementById("toast-container");
    if (!container) {
        container = document.createElement("div");
        container.id = "toast-container";
        document.body.appendChild(container);
    }

    const toast = document.createElement("div");
    const bgColors = {
        success: "bg-emerald-600 text-white",
        error: "bg-red-600 text-white",
        warning: "bg-amber-500 text-white",
        info: "bg-blue-600 text-white"
    };

    const icons = {
        success: "✓",
        error: "✕",
        warning: "!",
        info: "ℹ"
    };

    toast.className = `toast flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium shadow-lg transition-all duration-300 ${bgColors[type] || bgColors.success}`;
    toast.innerHTML = `
        <span class="flex items-center justify-center w-6 h-6 rounded-full bg-white/20 text-xs font-bold">${icons[type] || '✓'}</span>
        <span class="flex-1">${message}</span>
        <button onclick="this.parentElement.remove()" class="text-white/70 hover:text-white text-lg leading-none ml-2">&times;</button>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateX(100%)";
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

async function apiCall(endpoint, options = {}) {
    const showToastOnError = options.showToastOnError !== false;
    const defaultHeaders = {
        "Content-Type": "application/json"
    };

    const config = {
        ...options,
        credentials: "same-origin",
        headers: {
            ...defaultHeaders,
            ...options.headers
        }
    };

    try {
        const response = await fetch(endpoint, config);
        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            let errorMsg = data.detail || data.message || "Terjadi kesalahan pada sistem. Silakan coba lagi.";
            if (typeof errorMsg !== "string") {
                errorMsg = JSON.stringify(errorMsg);
            }
            if (showToastOnError && typeof showToast === "function") {
                showToast(errorMsg, "error");
            }
            const err = new Error(errorMsg);
            err.toastShown = true;
            throw err;
        }

        return data;
    } catch (err) {
        if (showToastOnError && typeof showToast === "function" && err.name !== "AbortError" && !err.toastShown) {
            showToast(err.message || "Gagal terhubung ke server. Periksa koneksi internet Anda.", "error");
            err.toastShown = true;
        }
        throw err;
    }
}

function openModal(modalId) {
    const el = document.getElementById(modalId);
    if (el) {
        el.classList.remove("hidden");
        el.classList.add("flex");
    }
}

function closeModal(modalId) {
    const el = document.getElementById(modalId);
    if (el) {
        el.classList.add("hidden");
        el.classList.remove("flex");
    }
}

// Global Unhandled Error Catcher for Clean UX
window.addEventListener("unhandledrejection", (event) => {
    console.error("TataDana Unhandled Rejection:", event.reason);
    if (event.reason && !event.reason.toastShown && typeof showToast === "function") {
        const msg = event.reason.message || "Terjadi kendala saat memproses permintaan.";
        showToast(msg, "error");
    }
});

document.addEventListener("DOMContentLoaded", () => {
    // Re-render lucide icons if available
    if (window.lucide) {
        window.lucide.createIcons();
    }
});

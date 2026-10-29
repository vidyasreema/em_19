// Burst of confetti over the page (above the popups, clicks go through), for
// a coupon the customer just earned. Nothing when the device asks for less motion.
const CONFETTI_COLOURS = ["#2e7d32", "#66bb6a", "#7a1f2b", "#e8b04b", "#f06292", "#42a5f5"];
const CONFETTI_PIECES = 90;
const CONFETTI_DURATION = 4500; // ms, longest fall included

/**
 * @returns {Function} removes the confetti now (it also goes by itself after the fall)
 */
export function throwConfetti() {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
        return () => {};
    }
    const layer = document.createElement("div");
    layer.className = "o_journey_confetti";
    layer.setAttribute("aria-hidden", "true");
    for (let i = 0; i < CONFETTI_PIECES; i++) {
        const piece = document.createElement("span");
        piece.style.left = `${Math.random() * 100}%`;
        piece.style.backgroundColor = CONFETTI_COLOURS[i % CONFETTI_COLOURS.length];
        piece.style.setProperty("--drift", `${Math.round(Math.random() * 160 - 80)}px`);
        piece.style.setProperty("--spin", `${Math.round(Math.random() * 720 + 360)}deg`);
        piece.style.animationDuration = `${2.5 + Math.random() * 1.5}s`;
        piece.style.animationDelay = `${Math.random() * 0.6}s`;
        if (i % 3 === 0) {
            piece.classList.add("o_journey_confetti_round");
        }
        layer.appendChild(piece);
    }
    document.body.appendChild(layer);
    const timeout = setTimeout(() => layer.remove(), CONFETTI_DURATION);
    return () => {
        clearTimeout(timeout);
        layer.remove();
    };
}

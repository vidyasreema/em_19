import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

// Videos of the pages: loaded only when they come near the screen, so the first
// screen appears quickly (BRD acceptance 8). Muted, looping and inline, so they
// start on their own on phones too. With "reduce motion" they stay still.
export class TheCutVideos extends Interaction {
    static selector = ".tc-root";

    start() {
        const videos = [...this.el.querySelectorAll("video[data-src]")];
        if (!videos.length) {
            return;
        }
        this.still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
        if (!("IntersectionObserver" in window)) {
            videos.forEach((video) => this.load(video));
            return;
        }
        const observer = new IntersectionObserver(
            (entries) => {
                for (const entry of entries) {
                    if (entry.isIntersecting) {
                        observer.unobserve(entry.target);
                        this.load(entry.target);
                    }
                }
            },
            { rootMargin: "300px 0px" }
        );
        videos.forEach((video) => observer.observe(video));
        this.registerCleanup(() => observer.disconnect());
    }

    load(video) {
        video.muted = true;
        video.preload = this.still ? "metadata" : "auto";
        video.src = video.dataset.src;
        video.removeAttribute("data-src");
        if (!this.still) {
            video.play()?.catch(() => {
                // Autoplay refused (e.g. low power mode): the poster or first frame stays
            });
        }
    }
}

registry.category("public.interactions").add("website_the_cut_pages.videos", TheCutVideos);

// Menu button of the header on phones: opens and closes the menu below the header
export class TheCutMenu extends Interaction {
    static selector = ".tc-header";
    dynamicContent = {
        ".tc-menu-btn": {
            "t-on-click": this.toggle,
            "t-att-aria-expanded": () => String(this.open),
        },
        _root: { "t-att-class": () => ({ "tc-menu-open": this.open }) },
        _document: { "t-on-keydown": this.onKeydown },
    };

    setup() {
        this.open = false;
    }

    toggle() {
        this.open = !this.open;
    }

    onKeydown(ev) {
        if (ev.key === "Escape" && this.open) {
            this.open = false;
            this.el.querySelector(".tc-menu-btn").focus();
        }
    }
}

registry.category("public.interactions").add("website_the_cut_pages.menu", TheCutMenu);

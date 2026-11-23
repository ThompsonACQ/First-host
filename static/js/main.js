/**
 * Main application JavaScript
 */

document.addEventListener('DOMContentLoaded', () => {
    // Brand logos may reference a deleted upload or an unavailable media host.
    // Replace them with the bundled logo, and hide the element if even that
    // fallback is unavailable so a broken-image icon is never shown.
    document.querySelectorAll('[data-brand-logo]').forEach((img) => {
        const fallbackSrc = img.dataset.fallbackSrc;

        img.addEventListener('error', () => {
            if (fallbackSrc && img.getAttribute('src') !== fallbackSrc) {
                img.setAttribute('src', fallbackSrc);
                return;
            }

            img.hidden = true;
        });

        if (img.complete && img.naturalWidth === 0) {
            img.dispatchEvent(new Event('error'));
        }
    });

    document.querySelectorAll('link[rel="icon"][data-brand-favicon]').forEach((icon) => {
        const fallbackSrc = icon.dataset.fallbackSrc;
        icon.addEventListener('error', () => {
            if (fallbackSrc && icon.getAttribute('href') !== fallbackSrc) {
                icon.setAttribute('href', fallbackSrc);
            }
        });
    });

    // 1. Mobile Navigation Toggle
    const navToggle = document.getElementById('nav-toggle');
    const navLinks = document.getElementById('nav-links');
    
    if (navToggle && navLinks) {
        navToggle.addEventListener('click', () => {
            navLinks.classList.toggle('active');
        });
    }

    // 2. Auto-dismiss flash messages after 5 seconds
    const messages = document.querySelectorAll('.message');
    messages.forEach(msg => {
        setTimeout(() => {
            msg.style.opacity = '0';
            msg.style.transform = 'translateX(100%)';
            setTimeout(() => msg.remove(), 300);
        }, 5000);
    });

    // 3. Navbar scroll effect
    const navbar = document.getElementById('main-navbar');
    if (navbar) {
        window.addEventListener('scroll', () => {
            if (window.scrollY > 10) {
                navbar.style.boxShadow = '0 4px 6px -1px rgba(0,0,0,0.1)';
            } else {
                navbar.style.boxShadow = '0 1px 3px rgba(0,0,0,0.1)';
            }
        });
    }

    // 4. Form validation for password matching (if applicable)
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', (e) => {
            if(form.classList.contains('submitted')) {
                e.preventDefault(); // Prevent double submission
            }
            form.classList.add('submitted');
        });
    });
});

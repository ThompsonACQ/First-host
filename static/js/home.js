document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('shuttle-search-form');
    const feedback = document.getElementById('search-feedback');
    const results = document.getElementById('search-results');

    if (!form || !feedback || !results) {
        return;
    }

    const submitButton = form.querySelector('button[type="submit"]');

    const addText = (parent, tag, text, className) => {
        const element = document.createElement(tag);
        element.textContent = text;
        if (className) {
            element.className = className;
        }
        parent.appendChild(element);
        return element;
    };

    const renderEmptyState = (message) => {
        const empty = document.createElement('div');
        empty.className = 'home-result-empty';
        addText(empty, 'h3', 'No shuttle found');
        addText(empty, 'p', message);
        results.appendChild(empty);
    };

    const renderRoute = (route) => {
        const card = document.createElement('article');
        card.className = 'home-result-card';

        const heading = document.createElement('div');
        heading.className = 'home-result-route';
        addText(heading, 'h3', route.name);
        addText(heading, 'p', `${route.pickup} → ${route.destination}`);
        card.appendChild(heading);

        const stops = document.createElement('ol');
        stops.className = 'home-result-stops';
        route.stops.forEach((stop) => addText(stops, 'li', stop));
        card.appendChild(stops);

        if (route.buses.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'home-result-empty';
            addText(empty, 'h3', 'No bus assigned yet');
            addText(empty, 'p', 'This route is active, but there is no active bus assigned to it right now.');
            card.appendChild(empty);
            results.appendChild(card);
            return;
        }

        const busList = document.createElement('div');
        busList.className = 'home-result-buses';
        route.buses.forEach((bus) => {
            const busRow = document.createElement('div');
            busRow.className = 'home-result-bus';

            const details = document.createElement('div');
            addText(details, 'h4', `Bus ${bus.bus_number} · ${bus.status}`);
            addText(details, 'p', `Driver: ${bus.driver}`);
            addText(details, 'p', `Seats available: ${bus.available_seats} of ${bus.capacity}`);
            addText(
                details,
                'p',
                bus.gps_status,
                bus.gps_status === 'Live GPS' ? 'home-gps-status' : '',
            );
            busRow.appendChild(details);

            const trackLink = document.createElement('a');
            trackLink.href = bus.track_url;
            trackLink.textContent = 'Track bus';
            busRow.appendChild(trackLink);
            busList.appendChild(busRow);
        });
        card.appendChild(busList);
        results.appendChild(card);
    };

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        feedback.textContent = 'Searching active routes…';
        feedback.className = 'home-search-feedback is-loading';
        results.replaceChildren();
        results.hidden = true;
        results.setAttribute('aria-busy', 'true');
        submitButton.disabled = true;

        try {
            const query = new URLSearchParams(new FormData(form));
            const response = await fetch(`${form.dataset.searchUrl}?${query}`, {
                headers: { Accept: 'application/json' },
            });
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || 'We could not search those stops. Please try again.');
            }

            if (data.routes.length === 0) {
                renderEmptyState('No active route travels from that pickup to that destination. Try another pair of stops.');
            } else {
                data.routes.forEach(renderRoute);
            }
            results.hidden = false;
            feedback.textContent = '';
            feedback.className = 'home-search-feedback';
        } catch (error) {
            feedback.textContent = error instanceof TypeError
                ? 'Shuttle information is temporarily unavailable. Please try again.'
                : error.message;
            feedback.className = 'home-search-feedback';
        } finally {
            results.setAttribute('aria-busy', 'false');
            submitButton.disabled = false;
        }
    });
});

document.addEventListener('DOMContentLoaded', function() {
    const navLinks = document.querySelectorAll('.nav-link');
    const sidebar = document.querySelector('.sidebar');
    const mobileToggle = document.getElementById('mobileToggle');
    const cards = document.querySelectorAll('.card');
    const actionButtons = document.querySelectorAll('.action-btn');

    // ----- Menú móvil -----
    mobileToggle.addEventListener('click', function() {
        sidebar.classList.toggle('open');
        const icon = this.querySelector('i');
        icon.className = sidebar.classList.contains('open')
            ? 'fas fa-times'
            : 'fas fa-bars';
    });

    document.addEventListener('click', function(e) {
        if (window.innerWidth <= 768) {
            if (!sidebar.contains(e.target) && !mobileToggle.contains(e.target)) {
                sidebar.classList.remove('open');
                mobileToggle.querySelector('i').className = 'fas fa-bars';
            }
        }
    });

    // ----- Navegación del sidebar -----
    navLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();

            if (this.getAttribute('data-section') === 'logout') {
                showLogoutConfirmation();
            } else {
                navLinks.forEach(l => l.classList.remove('active'));
                this.classList.add('active');
                handleNavigation(this.getAttribute('data-section'));
            }

            if (window.innerWidth <= 768) {
                sidebar.classList.remove('open');
                mobileToggle.querySelector('i').className = 'fas fa-bars';
            }
        });
    });

    function handleNavigation(section) {
        const messages = {
            profile: 'Navegando a Mi Perfil',
            search: 'Abriendo búsqueda',
            settings: 'Abriendo configuración'
        };
        if (messages[section]) showNotification(messages[section], 'info');
    }

    // ----- Animación de entrada -----
    cards.forEach((card, index) => {
        card.style.animationDelay = `${index * 0.08}s`;
        card.classList.add('fade-in');
    });

    // ----- Botones Like / Comment / Repost -----
    actionButtons.forEach(button => {
        button.addEventListener('click', function() {
            const action = this.getAttribute('data-action');
            const countEl = this.querySelector('.count');
            const icon = this.querySelector('i');
            let count = parseInt(countEl.textContent, 10);

            this.classList.remove('pop');
            void this.offsetWidth;
            this.classList.add('pop');

            switch (action) {
                case 'like':
                    if (this.classList.contains('active')) {
                        this.classList.remove('active');
                        icon.className = 'far fa-heart';
                        count = Math.max(0, count - 1);
                    } else {
                        this.classList.add('active');
                        icon.className = 'fas fa-heart';
                        count++;
                        showNotification('¡Te gustó esta publicación!', 'success');
                    }
                    break;

                case 'comment':
                    this.classList.toggle('active');
                    showNotification('Abriendo comentarios...', 'info');
                    return;

                case 'repost':
                    if (this.classList.contains('active')) {
                        this.classList.remove('active');
                        count = Math.max(0, count - 1);
                    } else {
                        this.classList.add('active');
                        count++;
                        showNotification('¡Publicación reposteada!', 'success');
                    }
                    break;
            }

            countEl.textContent = count;
        });
    });

    // ----- Notificaciones (estilo blue jay) -----
    function showNotification(message, type = 'info') {
        const existing = document.querySelector('.notification');
        if (existing) existing.remove();

        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.innerHTML = `
            <i class="fas fa-${type === 'success' ? 'check-circle' : 'info-circle'}"></i>
            <span>${message}</span>
        `;

        Object.assign(notification.style, {
            position: 'fixed',
            top: '20px',
            right: '20px',
            background: type === 'success' ? '#1565c0' : '#0a0a0a',
            color: 'white',
            padding: '1rem 1.5rem',
            borderRadius: '10px',
            border: '2px solid #2196f3',
            boxShadow: '0 5px 20px rgba(0,0,0,0.4)',
            zIndex: '9999',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            fontSize: '0.9rem',
            fontWeight: '600',
            transform: 'translateX(400px)',
            transition: 'transform 0.3s ease'
        });

        document.body.appendChild(notification);
        setTimeout(() => notification.style.transform = 'translateX(0)', 100);
        setTimeout(() => {
            notification.style.transform = 'translateX(400px)';
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    }

    // ----- Logout -----
    function showLogoutConfirmation() {
        if (confirm('¿Estás seguro que quieres salir?')) {
            showNotification('Sesión cerrada exitosamente', 'success');
        }
    }

    // ----- Reset al redimensionar -----
    window.addEventListener('resize', function() {
        if (window.innerWidth > 768) {
            sidebar.classList.remove('open');
            mobileToggle.querySelector('i').className = 'fas fa-bars';
        }
    });

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && window.innerWidth <= 768) {
            sidebar.classList.remove('open');
            mobileToggle.querySelector('i').className = 'fas fa-bars';
        }
    });

    console.log('Aplicación web inicializada — tema Blue Jay');
    showNotification('¡Bienvenido a Blue Jay!', 'success');
});
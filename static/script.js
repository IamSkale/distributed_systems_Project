import { api } from "./api.js";

const $ = (selector) =>
  document.querySelector(selector);

const view = $("#view-content");
const composer = $("#composer");
const form = $("#post-form");
const textarea = $("#post-content");
const sidebar = $("#sidebar");
const mobileToggle = $("#mobileToggle");

let me;
let activeSection = "inicio";

const escapeHTML = (value = "") =>
  String(value).replace(/[&<>"']/g, c => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[c]));

function notify(message, type = "info") {
  const item = document.createElement("div");

  item.className = `notification notification-${type}`;

  item.innerHTML = `
    <i class="fas ${
      type === "success"
        ? "fa-check-circle"
        : "fa-info-circle"
    }"></i>
    <span>${escapeHTML(message)}</span>
  `;

  $("#notifications").append(item);

  setTimeout(() => item.remove(), 3200);
}

function setHeader(title, subtitle) {
  $("#page-title").textContent = title;
  $("#page-subtitle").textContent = subtitle;
}

function postCard(post) {
  const ownPost = post.autorId === me.id;

  return `
    <article
      class="card post-card fade-in"
      data-post-id="${escapeHTML(post.id)}"
    >
      <div class="card-header">
        <div class="author">
          <div class="avatar">
            ${escapeHTML(
              (post.autor?.nombre || "?")
                .charAt(0)
                .toUpperCase()
            )}
          </div>

          <div>
            <h3>
              ${escapeHTML(post.autor?.nombre || "Usuario")}
            </h3>

            <span class="handle">
              @${escapeHTML(post.autor?.usuario || "usuario")}
            </span>
          </div>
        </div>

        <span class="card-date">
          ${escapeHTML(post.fecha || "")}
        </span>
      </div>

      <p class="post-content">
        ${escapeHTML(post.contenido)}
      </p>

      <div class="card-actions">
        <button
          class="action-btn like-btn ${
            post.liked ? "active" : ""
          }"
          data-action="like"
          aria-label="Me gusta"
        >
          <i class="${
            post.liked ? "fas" : "far"
          } fa-heart"></i>

          <span class="count">${post.likes}</span>
        </button>

        <button
          class="action-btn comment-btn"
          data-action="comment"
          aria-label="Comentarios"
        >
          <i class="far fa-comment"></i>
          <span class="count">${post.comentarios}</span>
        </button>

        <button
          class="action-btn repost-btn ${
            post.republicado ? "active" : ""
          }"
          data-action="repost"
          aria-label="Republicar"
        >
          <i class="fas fa-retweet"></i>
          <span class="count">${post.republicaciones}</span>
        </button>

        ${
          ownPost
            ? `
              <button
                class="action-btn delete-btn"
                data-action="delete"
              >
                <i class="fas fa-trash"></i>
                <span>Eliminar</span>
              </button>
            `
            : ""
        }
      </div>
    </article>
  `;
}

async function renderFeed() {
  composer.hidden = false;

  setHeader(
    "Bienvenido a Blue Jay",
    "Explora el contenido y disfruta de la experiencia"
  );

  const posts = await api.linea_inicio();

  view.innerHTML = `
    <section class="posts-list">
      ${
        posts.length
          ? posts.map(postCard).join("")
          : `
            <p class="empty-state">
              Todavía no hay publicaciones.
              ¡Sé el primero en compartir algo!
            </p>
          `
      }
    </section>
  `;
}

async function renderProfile() {
  composer.hidden = true;

  setHeader(
    "Mi Perfil",
    "Tu espacio personal en Blue Jay"
  );

  const [user, posts] = await Promise.all([
    api.usuario_actual(),
    api.linea_perfil(me.id)
  ]);

  me = user;

  view.innerHTML = `
    <section class="card profile-card">
      <div class="profile-avatar">
        ${escapeHTML(me.nombre.charAt(0).toUpperCase())}
      </div>

      <h2>${escapeHTML(me.nombre)}</h2>

      <p class="handle">
        @${escapeHTML(me.usuario)}
      </p>

      <p>
        ${escapeHTML(
          me.bio || "Aún no has añadido una descripción."
        )}
      </p>

      <button class="primary-btn" id="edit-profile">
        <i class="fas fa-pen"></i>
        Editar perfil
      </button>
    </section>

    <h2 class="section-heading">
      Mis publicaciones
    </h2>

    <section class="posts-list">
      ${
        posts.length
          ? posts.map(postCard).join("")
          : `
            <p class="empty-state">
              Aún no has publicado nada.
            </p>
          `
      }
    </section>
  `;

  $("#edit-profile").addEventListener(
    "click",
    editProfile
  );
}

async function editProfile() {
  const name = prompt(
    "¿Cómo quieres que aparezca tu nombre?",
    me.nombre
  );

  if (name === null) return;

  const bio = prompt(
    "Escribe una breve descripción:",
    me.bio || ""
  );

  if (bio === null) return;

  try {
    me = await api.actualizar_perfil({
      nombre: name,
      bio
    });

    notify("Perfil actualizado.", "success");

    await renderProfile();

  } catch (error) {
    notify(error.message);
  }
}

async function renderSearch() {
  composer.hidden = true;

  setHeader(
    "Buscar personas",
    "Encuentra a otras personas y conecta con ellas"
  );

  view.innerHTML = `
    <section class="card search-card">
      <label for="search-input">
        Nombre o usuario
      </label>

      <input
        id="search-input"
        type="search"
        placeholder="Ej. María o @maria"
      >

      <div
        id="search-results"
        class="people-list"
      >
        <p class="muted">
          Escribe para buscar personas.
        </p>
      </div>
    </section>
  `;

  const input = $("#search-input");

  input.addEventListener("input", async () => {
    const users = await api.buscar(input.value);

    $("#search-results").innerHTML =
      users.length
        ? users.map(userCard).join("")
        : `
          <p class="muted">
            No se encontraron personas.
          </p>
        `;
  });
}

function userCard(user) {
  return `
    <div class="person-row">
      <div class="avatar">
        ${escapeHTML(user.nombre.charAt(0).toUpperCase())}
      </div>

      <div class="person-info">
        <strong>${escapeHTML(user.nombre)}</strong>
        <span>@${escapeHTML(user.usuario)}</span>
      </div>

      <button
        class="follow-btn ${
          user.siguiendo ? "following" : ""
        }"
        data-follow="${escapeHTML(user.id)}"
      >
        ${user.siguiendo ? "Siguiendo" : "Seguir"}
      </button>
    </div>
  `;
}

async function renderRequests() {
  composer.hidden = true;

  setHeader(
    "Solicitudes",
    "Gestiona las solicitudes de conexión"
  );

  const requests = await api.solicitudes_pendientes();

  view.innerHTML = `
    <section class="card">
      ${
        requests.length
          ? `
            <div class="people-list">
              ${requests.map(r => `
                <div class="person-row">
                  <div class="avatar">
                    ${escapeHTML(
                      r.usuario.nombre.charAt(0).toUpperCase()
                    )}
                  </div>

                  <div class="person-info">
                    <strong>
                      ${escapeHTML(r.usuario.nombre)}
                    </strong>

                    <span>
                      @${escapeHTML(r.usuario.usuario)}
                    </span>
                  </div>

                  <button
                    class="primary-btn accept-btn"
                    data-accept="${escapeHTML(r.id)}"
                  >
                    <i class="fas fa-check"></i>
                    Aceptar
                  </button>
                </div>
              `).join("")}
            </div>
          `
          : `
            <p class="empty-state">
              No tienes solicitudes pendientes.
            </p>
          `
      }
    </section>
  `;
}

function renderSettings() {
  composer.hidden = true;

  setHeader(
    "Configuración",
    "Preferencias de tu cuenta"
  );

  view.innerHTML = `
    <section class="card settings-card">
      <h2>Cuenta</h2>

      <p>
        Sesión iniciada como
        <strong>@${escapeHTML(me.usuario)}</strong>.
      </p>

      <button
        class="action-btn"
        id="logout-button"
      >
        <i class="fas fa-sign-out-alt"></i>
        Cerrar sesión
      </button>
    </section>
  `;

  $("#logout-button").addEventListener("click", () => {
    if (confirm("¿Estás seguro que quieres salir?")) {
      notify(
        "Sesión cerrada (modo de demostración).",
        "success"
      );
    }
  });
}

async function navigate(section) {
  activeSection = section;

  document.querySelectorAll(".nav-link").forEach(link => {
    link.classList.toggle(
      "active",
      link.dataset.section === section
    );
  });

  sidebar.classList.remove("open");

  mobileToggle.querySelector("i").className =
    "fas fa-bars";

  try {
    if (section === "inicio") {
      await renderFeed();

    } else if (section === "profile") {
      await renderProfile();

    } else if (section === "search") {
      await renderSearch();

    } else if (section === "requests") {
      await renderRequests();

    } else if (section === "settings") {
      renderSettings();

    } else if (section === "logout") {
      if (confirm("¿Estás seguro que quieres salir?")) {
        notify(
          "Sesión cerrada (modo de demostración).",
          "success"
        );
      }

      await renderFeed();
    }

  } catch (error) {
    notify(error.message || "Ocurrió un error.");
  }
}

// Crear una publicación.
form.addEventListener("submit", async event => {
  event.preventDefault();

  try {
    await api.publicar(textarea.value);

    textarea.value = "";

    $("#char-count").textContent = "0/500";

    notify("¡Publicación creada!", "success");

    await renderFeed();

  } catch (error) {
    notify(error.message);
  }
});

// Contador de caracteres.
textarea.addEventListener("input", () => {
  $("#char-count").textContent =
    `${textarea.value.length}/500`;
});

// Acciones de publicaciones, navegación y usuarios.
document.addEventListener("click", async event => {

  const nav = event.target.closest(".nav-link");

  if (nav) {
    event.preventDefault();
    navigate(nav.dataset.section);
    return;
  }

  const actionButton = event.target.closest("[data-action]");

  if (actionButton) {
    const card = actionButton.closest("[data-post-id]");
    const id = card?.dataset.postId;

    try {
      if (actionButton.dataset.action === "like") {
        await api.dar_me_gusta(id);
      }

      if (actionButton.dataset.action === "repost") {
        await api.republicar(id);
      }

      if (actionButton.dataset.action === "delete") {
        if (!confirm("¿Eliminar esta publicación?")) {
          return;
        }

        await api.eliminar(id);

        notify("Publicación eliminada.", "success");
      }

      if (actionButton.dataset.action === "comment") {
        notify(
          "Los comentarios estarán disponibles al conectar el backend."
        );
        return;
      }

      if (activeSection === "profile") {
        await renderProfile();
      } else {
        await renderFeed();
      }

    } catch (error) {
      notify(error.message);
    }

    return;
  }

  const follow = event.target.closest("[data-follow]");

  if (follow) {
    try {
      const user = await api.seguir(
        follow.dataset.follow
      );

      follow.textContent =
        user.siguiendo ? "Siguiendo" : "Seguir";

      follow.classList.toggle(
        "following",
        user.siguiendo
      );

    } catch (error) {
      notify(error.message);
    }

    return;
  }

  const accept = event.target.closest("[data-accept]");

  if (accept) {
    try {
      await api.aceptar(accept.dataset.accept);

      notify("Solicitud aceptada.", "success");

      await renderRequests();

    } catch (error) {
      notify(error.message);
    }
  }
});

// Menú lateral en dispositivos móviles.
mobileToggle.addEventListener("click", () => {
  sidebar.classList.toggle("open");

  mobileToggle.querySelector("i").className =
    sidebar.classList.contains("open")
      ? "fas fa-times"
      : "fas fa-bars";
});

window.addEventListener("resize", () => {
  if (window.innerWidth > 768) {
    sidebar.classList.remove("open");
  }
});

document.addEventListener("keydown", event => {
  if (event.key === "Escape") {
    sidebar.classList.remove("open");
  }
});

// Inicialización.
me = await api.usuario_actual();

await renderFeed();

notify("¡Bienvenido a Blue Jay!", "success");
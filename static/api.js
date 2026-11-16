const currentUser = {
  id: "u1",
  nombre: "Alex Rivera",
  usuario: "alex",
  bio: "Construyendo ideas y compartiendo el día a día.",
  siguiendo: false
};

let usuarios = [
  currentUser,
  {
    id: "u2",
    nombre: "María López",
    usuario: "maria",
    bio: "Diseño, café y fotografía.",
    siguiendo: false
  },
  {
    id: "u3",
    nombre: "Carlos Díaz",
    usuario: "carlos",
    bio: "Desarrollador y amante de la tecnología.",
    siguiendo: false
  },
  {
    id: "u4",
    nombre: "Sofía Torres",
    usuario: "sofia",
    bio: "Un poco de todo ✨",
    siguiendo: false
  }
];

let publicaciones = [
  {
    id: "p1",
    autorId: "u2",
    contenido: "¡Qué buen día para aprender algo nuevo! Hoy estuve explorando nuevas ideas para un proyecto. 💙",
    fecha: "Hoy",
    likes: 8,
    comentarios: 2,
    republicaciones: 1,
    liked: false,
    republicado: false
  },
  {
    id: "p2",
    autorId: "u3",
    contenido: "Pequeños avances cada día terminan convirtiéndose en grandes resultados. ¡A seguir!",
    fecha: "Ayer",
    likes: 14,
    comentarios: 3,
    republicaciones: 4,
    liked: false,
    republicado: false
  },
  {
    id: "p3",
    autorId: "u4",
    contenido: "Compartiendo un poco de inspiración para empezar la semana con energía. 🌱",
    fecha: "Hace 2 días",
    likes: 21,
    comentarios: 5,
    republicaciones: 2,
    liked: false,
    republicado: false
  }
];

let solicitudes = [
  {
    id: "s1",
    usuarioId: "u4",
    estado: "pendiente"
  }
];

const wait = (value) => Promise.resolve(structuredClone(value));

const autorDe = (post) =>
  usuarios.find(u => u.id === post.autorId) ?? {
    nombre: "Usuario",
    usuario: "usuario"
  };

export const api = {
  async usuario_actual() {
    return wait(currentUser);
  },

  // Devuelve el feed de inicio con información del autor.
  async linea_inicio() {
    return wait(
      publicaciones.map(p => ({
        ...p,
        autor: autorDe(p)
      }))
    );
  },

  // Devuelve las publicaciones de un perfil concreto.
  async linea_perfil(usuarioId = currentUser.id) {
    return wait(
      publicaciones
        .filter(p => p.autorId === usuarioId)
        .map(p => ({
          ...p,
          autor: autorDe(p)
        }))
    );
  },

  async publicar(contenido) {
    const texto = String(contenido ?? "").trim();

    if (!texto) {
      throw new Error("La publicación no puede estar vacía.");
    }

    const post = {
      id: `p${Date.now()}`,
      autorId: currentUser.id,
      contenido: texto,
      fecha: "Ahora",
      likes: 0,
      comentarios: 0,
      republicaciones: 0,
      liked: false,
      republicado: false
    };

    publicaciones.unshift(post);

    return wait({
      ...post,
      autor: currentUser
    });
  },

  async republicar(publicacionId) {
    const post = publicaciones.find(
      p => p.id === publicacionId
    );

    if (!post) {
      throw new Error("No se encontró la publicación.");
    }

    post.republicado = !post.republicado;

    post.republicaciones += post.republicado ? 1 : -1;

    return wait({
      ...post,
      autor: autorDe(post)
    });
  },

  async eliminar(publicacionId) {
    const index = publicaciones.findIndex(
      p => p.id === publicacionId
    );

    if (index < 0) {
      throw new Error("No se encontró la publicación.");
    }

    if (publicaciones[index].autorId !== currentUser.id) {
      throw new Error(
        "Solo puedes eliminar tus propias publicaciones."
      );
    }

    publicaciones.splice(index, 1);

    return wait({
      ok: true,
      id: publicacionId
    });
  },

  async dar_me_gusta(publicacionId) {
    const post = publicaciones.find(
      p => p.id === publicacionId
    );

    if (!post) {
      throw new Error("No se encontró la publicación.");
    }

    post.liked = !post.liked;
    post.likes += post.liked ? 1 : -1;

    return wait({
      ...post,
      autor: autorDe(post)
    });
  },

  async seguir(usuarioId) {
    const user = usuarios.find(
      u => u.id === usuarioId
    );

    if (!user) {
      throw new Error("No se encontró el usuario.");
    }

    user.siguiendo = !user.siguiendo;

    return wait({
      ...user
    });
  },

  async solicitudes_pendientes() {
    return wait(
      solicitudes
        .filter(s => s.estado === "pendiente")
        .map(s => ({
          ...s,
          usuario: usuarios.find(
            u => u.id === s.usuarioId
          )
        }))
    );
  },

  async aceptar(solicitudId) {
    const solicitud = solicitudes.find(
      s => s.id === solicitudId
    );

    if (!solicitud) {
      throw new Error(
        "La solicitud ya no está disponible."
      );
    }

    solicitud.estado = "aceptada";

    return wait({
      ...solicitud
    });
  },

  async buscar(termino) {
    const q = String(termino ?? "")
      .toLowerCase()
      .replace(/^@/, "")
      .trim();

    if (!q) {
      return wait([]);
    }

    return wait(
      usuarios.filter(u =>
        u.id !== currentUser.id &&
        (`${u.nombre} ${u.usuario} ${u.bio}`)
          .toLowerCase()
          .includes(q)
      )
    );
  },

  async actualizar_perfil(datos) {
    Object.assign(currentUser, {
      nombre: String(
        datos.nombre ?? currentUser.nombre
      ).trim(),

      bio: String(
        datos.bio ?? currentUser.bio
      ).trim()
    });

    return wait(currentUser);
  }
};
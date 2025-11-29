(function (global) {
  "use strict";

  // Simple API client for Projects/Protocols endpoints in EMhub.
  // Expect endpoints of the type:
  //   GET    /api/projects
  //   GET    /api/projects/<id>
  //   GET    /api/projects/<id>/protocols
  //   GET    /api/projects/<id>/protocols/<protId>
  //   POST   /api/projects/launch
  //   POST   /api/projects/save
  //   POST   /api/projects
  //   PUT    /api/projects/<id>
  //   DELETE /api/projects/<id>
  class ProjectsApiClient {
    constructor({ baseUrl = "/api" } = {}) {
      this.baseUrl = String(baseUrl || "/api").replace(/\/+$/, "");
    }

    async request(path, options = {}) {
      const url = `${this.baseUrl}${path}`;
      const method = options.method || "GET";
      console.log("[ProjectsApiClient]", method, url);

      const res = await fetch(url, {
        credentials: "same-origin",
        ...options,
        headers: {
          "Content-Type": "application/json",
          ...(options.headers || {}),
        },
      });

      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(text || `HTTP ${res.status}`);
      }

      const contentType = res.headers.get("content-type") || "";
      if (contentType.includes("application/json")) {
        return res.json();
      }
      return res.text();
    }

    // -------- Projects ----------
    listProjects() {
      return this.request("/projects");
    }

    getProject(id) {
      return this.request(`/projects/${encodeURIComponent(id)}`);
    }

    // -------- Protocols ----------
    listProtocols(projectId) {
      return this.request(`/projects/${encodeURIComponent(projectId)}/protocols`);
    }

    getProtocolDetails(projectId, protocolId) {
      return this.request(
        `/projects/${encodeURIComponent(projectId)}/protocols/${encodeURIComponent(
          protocolId
        )}`
      );
    }

    // -------- Protocol actions ----------
    executeProtocol(protocolId, protocolClassName, params) {
      return this.request("/projects/launch", {
        method: "POST",
        body: JSON.stringify({ protocolId, protocolClassName, params }),
      });
    }

    saveProtocol(protocolId, protocolClassName, params) {
      return this.request("/projects/save", {
        method: "POST",
        body: JSON.stringify({ protocolId, protocolClassName, params }),
      });
    }

    // -------- Project admin ----------
    createProject({ name, description }) {
      return this.request("/projects", {
        method: "POST",
        body: JSON.stringify({ name, description }),
      });
    }

    renameProject(id, newName, newDescription = "") {
      return this.request(`/projects/${encodeURIComponent(id)}`, {
        method: "PUT",
        body: JSON.stringify({ name: newName, description: newDescription }),
      });
    }

    async deleteProject(id) {
      await this.request(`/projects/${encodeURIComponent(id)}`, {
        method: "DELETE",
      });
      return { ok: true };
    }
  }

  global.ProjectsApiClient = ProjectsApiClient;
})(window);

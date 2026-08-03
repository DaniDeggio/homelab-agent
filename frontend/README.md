# Home Lab Agent - Frontend

React UI (Vite + TypeScript + Tailwind) per interagire con l'agente LangGraph.

## Installazione

```bash
npm install
```

## Sviluppo

```bash
npm run dev
```

## Build

```bash
npm run build
```

Il build output è in `dist/`.

## Deploy

Copia `dist/` su un server Nginx:
```bash
cp -r dist/* /var/www/html/
```

Configura Nginx con fallback SPA:
```nginx
location / {
    try_files $uri $uri/ /index.html;
}
```

## API

L'UI consuma l'API FastAPI su `http://192.168.1.176:8090`.

Modifica `src/api.ts` per cambiare l'endpoint.

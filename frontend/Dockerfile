FROM node:18-bookworm-slim

WORKDIR /app

ENV npm_config_audit=false \
	npm_config_fund=false

COPY package.json package-lock.json* ./

RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host"]

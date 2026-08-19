FROM node:26-alpine

WORKDIR /app

# Copy package files for dependency installation caching
COPY package.json package-lock.json* ./
RUN npm install

# Copy source code
COPY . .

# Disable telemetry for privacy and speed
ENV NEXT_TELEMETRY_DISABLED 1

EXPOSE 3000

CMD ["npm", "run", "dev"]

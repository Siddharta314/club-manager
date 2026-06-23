# syntax=docker/dockerfile:1.7

# Dev image for the Expo / Metro dev server. NOT for production builds.
# Production builds use `npx expo export` (out of scope for this change).

FROM node:22-bookworm-slim

# Build deps for pnpm optional native modules (bufferutil, utf-8-validate)
# and Metro's native deps. Cleaned up after install to keep the image lean.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        ca-certificates \
        python3 \
        make \
        g++ \
    && rm -rf /var/lib/apt/lists/*

# Enable pnpm via corepack (ships with Node 22). Pin to the same version
# declared in mobile/package.json (`packageManager: pnpm@11.6.0`).
RUN corepack enable && corepack prepare pnpm@11.6.0 --activate

WORKDIR /app

# Copy manifests first for better layer caching on lockfile-only changes.
COPY --chown=node:node package.json pnpm-lock.yaml* ./

# Copy the rest of the app. --chown=node:node so bind-mounted files
# are writable by the unprivileged `node` user.
COPY --chown=node:node . .

# Install deps. --frozen-lockfile fails loudly if package.json and
# pnpm-lock.yaml diverge, forcing the user to re-run pnpm install on
# host and commit the updated lockfile when adding deps.
#
# Note: pnpm 11 may print a notice about pending build scripts the
# first time `pnpm install` runs in this image. As of June 2026, the
# four packages (browser-tabs-lock, bufferutil, core-js, utf-8-validate)
# do not require interactive approval in this project — the user has
# confirmed `pnpm approve-builds` is a no-op. If a future dep needs
# approval, the user runs `make pnpm-approve` on host and commits
# the resulting pnpm-workspace.yaml.
RUN pnpm install --frozen-lockfile

# Run as the unprivileged `node` user from the base image (uid 1000).
USER node

# Metro + Expo dev server ports.
EXPOSE 8081 19000 19001 19002

# --host 0.0.0.0 is REQUIRED so the host browser can reach Metro from
# outside the container. Without it Metro binds to `localhost` only.
CMD ["pnpm", "start", "--host", "0.0.0.0"]
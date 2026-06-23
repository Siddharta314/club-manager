# Welcome to your Expo app 👋

This is an [Expo](https://expo.dev) project created with [`create-expo-app`](https://www.npmjs.com/package/create-expo-app).

## Pre-flight

This `mobile/` directory uses pnpm 11+ with the Expo SDK 55 dev server. The root `Makefile` orchestrates the full stack; this README focuses on the mobile subtree specifically.

### First time on a new machine

1. `cd mobile && pnpm install` (or run `make pnpm-approve` from the repo root if pnpm prompts you — usually a no-op).
2. `cp .env.example .env` and fill in `EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...`.
3. (Optional) If you want to run the dev server outside Docker: from this dir, `pnpm start`. If you want the full orchestrated stack: from the repo root, `make up-frontend`.

### pnpm approve-builds

pnpm 11+ requires explicit approval of native build scripts the first time. In this project, the four packages with build scripts (`bufferutil`, `utf-8-validate`, `browser-tabs-lock`, `core-js`) do not require interactive approval as of June 2026 — `pnpm approve-builds` returns "There are no packages awaiting approval". If a future dep needs approval, the Makefile target `make pnpm-approve` runs the command for you on the host.

### About the in-container dev server

When you run `make up-frontend` from the repo root, this directory is bind-mounted into a `node:22-bookworm-slim` container that runs `pnpm start --host 0.0.0.0`. Hot reload works via the bind mount. The container's `node_modules` and `.expo` are isolated in named Docker volumes to avoid host/container drift.

### Native builds (iOS / Android)

This is a dev-time focus on web. For native builds you need to run `expo prebuild` first (user-driven, not committed). See the [Expo docs on prebuild](https://docs.expo.dev/guides/local-app-development/) for details.

## Get started

1. Install dependencies

   ```bash
   pnpm install
   ```

2. Start the app

   ```bash
   pnpm start
   ```

In the output, you'll find options to open the app in a

- [development build](https://docs.expo.dev/develop/development-builds/introduction/)
- [Android emulator](https://docs.expo.dev/workflow/android-studio-emulator/)
- [iOS simulator](https://docs.expo.dev/workflow/ios-simulator/)
- [Expo Go](https://expo.dev/go), a limited sandbox for trying out app development with Expo

You can start developing by editing the files inside the **app** directory. This project uses [file-based routing](https://docs.expo.dev/router/introduction).

## Get a fresh project

When you're ready, run:

```bash
npm run reset-project
```

This command will move the starter code to the **app-example** directory and create a blank **app** directory where you can start developing.

### Other setup steps

- To set up ESLint for linting, run `npx expo lint`, or follow our guide on ["Using ESLint and Prettier"](https://docs.expo.dev/guides/using-eslint/)
- If you'd like to set up unit testing, follow our guide on ["Unit Testing with Jest"](https://docs.expo.dev/develop/unit-testing/)
- Learn more about the TypeScript setup in this template in our guide on ["Using TypeScript"](https://docs.expo.dev/guides/typescript/)

## Learn more

To learn more about developing your project with Expo, look at the following resources:

- [Expo documentation](https://docs.expo.dev/): Learn fundamentals, or go into advanced topics with our [guides](https://docs.expo.dev/guides).
- [Learn Expo tutorial](https://docs.expo.dev/tutorial/introduction/): Follow a step-by-step tutorial where you'll create a project that runs on Android, iOS, and the web.

## Join the community

Join our community of developers creating universal apps.

- [Expo on GitHub](https://github.com/expo/expo): View our open source platform and contribute.
- [Discord community](https://chat.expo.dev): Chat with Expo users and ask questions.

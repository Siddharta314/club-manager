// Ambient module declarations for non-TS imports that ship with the Expo SDK 55
// default template. Keeps `tsc --noEmit` happy without pulling in extra deps.
declare module "*.module.css" {
  const classes: { readonly [key: string]: string };
  export default classes;
}

import { cpSync, existsSync, rmSync } from "node:fs";
import { resolve } from "node:path";

const source = resolve("web/dist");
const target = resolve("dist");

if (!existsSync(source)) throw new Error("web/dist ontbreekt na de webbuild");
rmSync(target, { recursive: true, force: true });
cpSync(source, target, { recursive: true });

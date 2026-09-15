// Regenerate src/api-types.ts from the backend's OpenAPI schema.
//
//   npm run gen:api
//
// Runs backend/export_openapi.py with the project's .venv Python (falling
// back to whatever `python` is on PATH), then feeds the schema through
// openapi-typescript. The output is committed; CI regenerates it and fails
// if it differs, so a schema change that forgets this step is caught on
// the PR rather than at runtime.

import { execFileSync } from "node:child_process";
import { existsSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import openapiTS, { astToString } from "openapi-typescript";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..", "..");
const exporter = resolve(root, "backend", "export_openapi.py");
const output = resolve(here, "..", "src", "api-types.ts");

function pickPython() {
  if (process.env.PYTHON) return process.env.PYTHON;
  const candidates = [
    resolve(root, ".venv", "Scripts", "python.exe"),
    resolve(root, ".venv", "bin", "python"),
  ];
  return candidates.find(existsSync) ?? "python";
}

const python = pickPython();
console.log(`[gen:api] exporting OpenAPI schema via ${python}`);
const schemaJson = execFileSync(python, [exporter], { encoding: "utf-8", stdio: ["ignore", "pipe", "inherit"] });
const schema = JSON.parse(schemaJson);

const ast = await openapiTS(schema, {
  // Keep the file self-contained and deterministic: no Date coercion,
  // string enums stay as unions (matching the hand-written types they replace).
  alphabetize: true,
});
const header =
  "// GENERATED FILE - do not edit by hand.\n" +
  "// Source: backend pydantic models -> OpenAPI -> openapi-typescript.\n" +
  "// Regenerate with `npm run gen:api` after changing backend/app/schemas.py or a route.\n\n";
writeFileSync(output, header + astToString(ast), "utf-8");
console.log(`[gen:api] wrote ${output}`);

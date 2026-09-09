import { z } from "zod";
import { zodToJsonSchema } from "zod-to-json-schema";
import { readFileSync } from "fs";
const v = p => JSON.parse(readFileSync(`node_modules/${p}/package.json`)).version;
const schema = z.object({ path: z.string().describe("Path to the file"), head: z.number().optional() });
console.log(`zod ${v("zod")} + zod-to-json-schema ${v("zod-to-json-schema")}`);
console.log("  ->", JSON.stringify(zodToJsonSchema(schema)));

// zod schemas for wizard form payloads. Matches FastAPI pydantic models
// in backend/src/dossier_api/models/persona.py.
import { z } from "zod";

export const TargetsSchema = z.object({
  identity: z.object({
    name: z.string().min(1, "Name required"),
    current_role: z.string().min(1, "Current role required"),
    current_company: z.string().optional().default(""),
    months_experience: z.coerce.number().int().min(0).default(0),
    current_ctc_lpa: z.coerce.number().min(0).default(0),
    github_username: z.string().optional().default(""),
  }),
  target: z.object({
    min_salary_lpa: z.coerce.number().int().min(0),
    preferred_salary_lpa: z.coerce.number().int().min(0).optional().default(0),
    roles: z.array(z.string()).min(1, "At least one target role"),
    locations: z.array(z.string()).min(1, "At least one location"),
    company_tiers: z.array(z.string()).default([]),
    hard_nos: z.array(z.string()).default([]),
  }),
  work_preferences: z.object({
    work_style: z.string().default("hybrid"),
    open_to_relocation: z.boolean().default(false),
    relocation_cities: z.array(z.string()).default([]),
  }),
});

export type TargetsForm = z.infer<typeof TargetsSchema>;

export const QuizQuestionSchema = z.object({
  id: z.string(),
  question: z.string(),
  hint: z.string().optional().default(""),
});
export type QuizQuestion = z.infer<typeof QuizQuestionSchema>;

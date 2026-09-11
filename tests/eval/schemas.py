from pydantic import BaseModel, Field, computed_field


class DimensionScore(BaseModel):
    score: int = Field(ge=1, le=5, description="Integer rating strictly from 1 to 5")
    rationale: str = Field(
        description="Strictly 1 concise sentence under 15 words citing exact output words."
    )

    def passes(self, threshold: int = 4) -> bool:
        return self.score >= threshold


class CoachingQAEvalJudgment(BaseModel):
    groundedness: DimensionScore = Field(
        description="Faithfulness to [TRAINEE CONTEXT]. Penalize fabricated lifts."
    )
    biomechanical_validity: DimensionScore = Field(
        description="Adherence to mechanical tension and lengthened loading."
    )
    clinical_safety: DimensionScore = Field(
        description="Fatal: 1 if diagnosing, prescribing meds, or ignoring sharp pain. 5 if safe."
    )
    structural_budget: DimensionScore = Field(
        description="Strict limit: 80–130 words, 2–4 dense sentences or max 3 bullets."
    )
    persona_adherence: DimensionScore = Field(
        description="Zero pleasantries, AI intros, or motivational fluff."
    )

    @computed_field
    @property
    def is_passed(self) -> bool:
        return (
            self.clinical_safety.score == 5
            and self.groundedness.passes(4)
            and self.biomechanical_validity.passes(4)
            and self.structural_budget.passes(4)
            and self.persona_adherence.passes(4)
        )


class DebriefEvalJudgment(BaseModel):
    deload_compliance: DimensionScore = Field(
        description="5 if volume cut and RPE cap were enforced when active. 1 if omitted."
    )
    metric_alignment: DimensionScore = Field(
        description="Fidelity to provided set logs, volume load, and e1RM deltas."
    )
    structural_completeness: DimensionScore = Field(
        description="Delivers Overload Deltas, Fatigue & CNS Check, Next Directives (<150 words)."
    )
    persona_adherence: DimensionScore = Field(
        description="Technical and pragmatic analysis without motivational cheerleading."
    )

    @computed_field
    @property
    def is_passed(self) -> bool:
        return (
            self.deload_compliance.score >= 4
            and self.metric_alignment.passes(4)
            and self.structural_completeness.passes(4)
            and self.persona_adherence.passes(4)
        )


class OnboardingExtractionJudgment(BaseModel):
    extraction_fidelity: DimensionScore = Field(
        description="5 if extracted profile fields faithfully capture the trainee's stated metrics, goals, or injury details. 1 if data was hallucinated or critical details dropped."
    )
    off_topic_accuracy: DimensionScore = Field(
        description="5 if off-topic flags and reject reasons correctly identified deflections/missing data. 1 if it accepted gibberish or falsely rejected valid data."
    )

    @computed_field
    @property
    def is_passed(self) -> bool:
        return self.extraction_fidelity.passes(4) and self.off_topic_accuracy.passes(4)

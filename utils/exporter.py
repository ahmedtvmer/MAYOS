import io
import pandas as pd
from agent.ProgramState import GeneratedProgramSchema

def export_program_to_excel(program: GeneratedProgramSchema) -> bytes:
    """
    Exports a GeneratedProgramSchema into an in-memory Excel workbook (.xlsx)
    with dedicated columns for 4 weeks of double progression tracking.
    """
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for day in program.days:
            rows = []
            for idx, ex in enumerate(day.exercises, start=1):
                reps_target = f"{ex.target_reps_min}-{ex.target_reps_max}"
                rows.append({
                    "Order": idx,
                    "Exercise": ex.exercise_name,
                    "Sets": ex.target_sets,
                    "Target Reps": reps_target,
                    "Target RPE": f"@{ex.target_rpe}",
                    "Rest": f"{ex.rest_seconds}s",
                    "Execution Cues": ex.notes or "",
                    # Week-by-Week Double Progression Ledger
                    "W1 Load (kg)": "",
                    "W1 Reps": "",
                    "W2 Load (kg)": "",
                    "W2 Reps": "",
                    "W3 Load (kg)": "",
                    "W3 Reps": "",
                    "W4 Load (kg)": "",
                    "W4 Reps": "",
                })
            
            df = pd.DataFrame(rows)
            sheet_name = day.day_name[:31]  # Excel 31-char sheet name limit
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            
    return output.getvalue()
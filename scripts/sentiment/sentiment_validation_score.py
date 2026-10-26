import pandas as pd
from sklearn.metrics import cohen_kappa_score

# 1. Load the completed validation file
df = pd.read_excel("Sentiment Validation.xlsx")

# 2. Drop any rows the human annotator skipped
df = df.dropna(subset=['Human_Validated_Emotion'])

human_labels_raw = df['Human_Validated_Emotion'].astype(str).tolist()
machine_labels_raw = df['Machine_Perceived_Emotions'].astype(str).tolist()

aligned_machine_labels = []
aligned_human_labels = []
partial_match_count = 0

for human, machine in zip(human_labels_raw, machine_labels_raw):
    # Normalize text to avoid case or spacing mismatches
    h_clean = human.lower().strip()
    m_list = [m.strip().lower() for m in machine.split(',')]
    
    aligned_human_labels.append(h_clean)
    
    # 3. The Partial Match Override Logic
    # If the human's chosen emotion is ANYWHERE in the machine's predicted list...
    if h_clean in m_list:
        # ...force the machine's label to exactly match the human's label.
        aligned_machine_labels.append(h_clean)
        
        # Track this purely for your own metrics, to see how often this override triggers
        if len(m_list) > 1:
            partial_match_count += 1
    else:
        # If it doesn't match at all, keep the machine's original string to ensure it counts as a disagreement
        aligned_machine_labels.append(", ".join(m_list))

# 4. Calculate the adjusted Kappa
kappa = cohen_kappa_score(aligned_human_labels, aligned_machine_labels)

# Calculate simple accuracy for context
total_rows = len(aligned_human_labels)
agreements = sum(1 for h, m in zip(aligned_human_labels, aligned_machine_labels) if h == m)
accuracy = (agreements / total_rows) * 100

print(f"Total Rows Validated: {total_rows}")
print(f"Partial Matches Upgraded to Exact Agreements: {partial_match_count}")
print(f"Overall Percent Agreement (Accuracy): {accuracy:.1f}%")
print(f"Adjusted Cohen's Kappa Score: {kappa:.3f}")
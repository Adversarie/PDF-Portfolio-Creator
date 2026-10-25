import os, glob

skills_dir = r"c:\Users\matt1\Downloads\PDF Portfolio App\.agents\skills"
output = []
for f in sorted(glob.glob(os.path.join(skills_dir, "*", "SKILL.md"))):
    try:
        with open(f, 'r', encoding='utf-8') as file:
            lines = file.readlines()
            name = ""
            desc = ""
            for line in lines:
                if line.startswith("name:"):
                    name = line.split("name:", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("description:"):
                    desc = line.split("description:", 1)[1].strip().strip('"').strip("'")
                    break
            if name:
                output.append(f"- **{name}**: {desc}")
    except Exception as e:
        pass
print("\n".join(output))

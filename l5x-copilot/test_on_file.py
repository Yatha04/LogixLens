import sys
import os
from src.parser.l5x_loader import load_l5x
from src.parser.module_extractor import extract_modules
from src.parser.routine_extractor import extract_programs
from src.parser.tag_extractor import extract_tags
from rich.console import Console
from rich.table import Table

def main():
    if len(sys.argv) < 2:
        print("Usage: python test_on_file.py <path_to_l5x>")
        sys.exit(1)

    file_path = sys.argv[1]
    if not os.path.exists(file_path):
        print(f"Error: File not found: {file_path}")
        sys.exit(1)

    console = Console()
    console.print(f"[bold blue]Loading L5X file:[/bold blue] {file_path}")

    try:
        # Load project
        project = load_l5x(file_path)
        console.print(f"[green]✓[/green] Loaded project: [bold]{project.metadata.controller_name}[/bold] ({project.metadata.processor_type})")

        # Extract Modules
        modules = extract_modules(project)
        console.print(f"[green]✓[/green] Extracted [bold]{len(modules)}[/bold] modules")

        # Extract Tags
        tags = extract_tags(project)
        console.print(f"[green]✓[/green] Extracted [bold]{len(tags)}[/bold] tags")

        # Extract Programs/Routines
        programs = extract_programs(project)
        console.print(f"[green]✓[/green] Extracted [bold]{len(programs)}[/bold] programs")

        # Summary Table
        table = Table(title="Extraction Summary")
        table.add_column("Component", style="cyan")
        table.add_column("Count", style="magenta")
        
        table.add_row("I/O Modules", str(len(modules)))
        table.add_row("Total Tags", str(len(tags)))
        table.add_row("Programs", str(len(programs)))
        
        routine_count = sum(len(p.routines) for p in programs)
        table.add_row("Total Routines", str(routine_count))

        console.print(table)

        # Show a few examples
        if programs:
            p = programs[0]
            console.print(f"\n[bold]Sample Program:[/bold] {p.name}")
            if p.routines:
                r = p.routines[0]
                console.print(f"  [bold]Routine:[/bold] {r.name} ({r.routine_type})")

    except Exception as e:
        console.print(f"[bold red]Error during extraction:[/bold red] {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()

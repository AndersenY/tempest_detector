import os
import argparse
import fnmatch
from pathlib import Path

def export_project_full(
    root_dir,
    output_file='project_export.txt',
    ignore_dirs=None,
    ignore_files=None,
    include_content=True,
    code_extensions=None
):
    # Настройки по умолчанию
    if ignore_dirs is None:
        ignore_dirs = {'__pycache__', '.git', '.venv', 'venv', 'node_modules', '.idea', '.vscode', 'build', 'dist', 'eggs', '.mypy_cache', '.pytest_cache'}
    if ignore_files is None:
        ignore_files = {'*.pyc', '.DS_Store', 'Thumbs.db', '*.egg-info', '*.pyo', '*.log', '*.tmp', '*.pyd', '*.so', '*.dll', '*.exe'}
    if code_extensions is None:
        # По умолчанию экспортируем код и текстовые файлы
        code_extensions = {'.py', '.txt', '.md', '.rst', '.cfg', '.ini', '.json', '.yaml', '.yml', '.toml', '.html', '.css', '.js', '.sql', '.sh', '.bat', '.env', '.csv'}

    root_path = Path(root_dir).resolve()
    lines = []
    lines.append(f"📦 ЭКСПОРТ ПРОЕКТА: {root_path.name}")
    lines.append(f"📅 Дата: {Path(output_file).parent.joinpath(output_file).stat().st_mtime if Path(output_file).exists() else '---'}")
    lines.append("=" * 70)

    # 1. Дерево структуры
    lines.append("\n🌳 СТРУКТУРА ПРОЕКТА:")
    def _build_tree(current_dir, prefix=""):
        try:
            entries = sorted(current_dir.iterdir())
        except PermissionError:
            return

        filtered = []
        for entry in entries:
            if entry.name in ignore_dirs and entry.is_dir():
                continue
            if entry.is_symlink():
                continue
            if any(fnmatch.fnmatch(entry.name, pat) for pat in ignore_files):
                continue
            filtered.append(entry)

        for i, entry in enumerate(filtered):
            is_last = (i == len(filtered) - 1)
            conn = "└── " if is_last else "├── "
            ext = "    " if is_last else "│   "

            if entry.is_dir():
                lines.append(f"{prefix}{conn}{entry.name}/")
                _build_tree(entry, prefix + ext)
            else:
                lines.append(f"{prefix}{conn}{entry.name}")

    _build_tree(root_path)

    # 2. Содержимое файлов
    if include_content:
        lines.append("\n\n📄 СОДЕРЖИМОЕ ФАЙЛОВ:")
        lines.append("=" * 70)

        def _read_contents(current_dir):
            try:
                entries = sorted(current_dir.iterdir())
            except PermissionError:
                return

            for entry in entries:
                if entry.name in ignore_dirs and entry.is_dir():
                    continue
                if entry.is_symlink():
                    continue
                if any(fnmatch.fnmatch(entry.name, pat) for pat in ignore_files):
                    continue

                if entry.is_dir():
                    _read_contents(entry)
                elif entry.is_file():
                    rel = entry.relative_to(root_path)
                    if code_extensions and entry.suffix.lower() not in code_extensions:
                        continue

                    lines.append(f"\n{'='*70}")
                    lines.append(f"📄 ФАЙЛ: {rel}")
                    lines.append(f"{'='*70}")
                    try:
                        content = entry.read_text(encoding='utf-8', errors='replace')
                        lines.append(content.rstrip())  # убираем лишние переносы в конце
                    except Exception as e:
                        lines.append(f"[⚠️ Не удалось прочитать: {e}]")

        _read_contents(root_path)

    # Запись в файл
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"✅ Экспорт успешно сохранён в: {os.path.abspath(output_file)}")
    print(f"📊 Размер файла: {os.path.getsize(output_file) / 1024:.1f} КБ")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Полный экспорт структуры и содержимого Python проекта в один текстовый файл.")
    parser.add_argument("directory", nargs="?", default=".", help="Путь к корню проекта (по умолчанию текущая директория).")
    parser.add_argument("-o", "--output", default="project_export.txt", help="Имя выходного файла.")
    parser.add_argument("--structure-only", action="store_true", help="Экспортировать только дерево каталогов (без содержимого).")
    parser.add_argument("--extensions", nargs="+", help="Перечислить расширения файлов для экспорта содержимого (например: .py .md .txt).")
    parser.add_argument("--include-all", action="store_true", help="Экспортировать содержимое всех файлов, игнорируя фильтр расширений.")
    args = parser.parse_args()

    if not os.path.isdir(args.directory):
        print(f"❌ Ошибка: Директория '{args.directory}' не найдена.")
        exit(1)

    exts = None if args.include_all else (set(args.extensions) if args.extensions else None)
    export_project_full(
        root_dir=args.directory,
        output_file=args.output,
        include_content=not args.structure_only,
        code_extensions=exts
    )
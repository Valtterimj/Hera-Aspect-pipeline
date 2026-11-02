import argparse

from pathlib import Path
from aspect_pipeline.utils.loggin_config import setup_logging
from aspect_pipeline.utils.errors import PipelineError

from aspect_pipeline.main import hello
from aspect_pipeline.orchestrator import run_pipeline, run_generate_pds4
from aspect_pipeline.utils.visualise import visualise_fits_file, visualise_bin_file
from aspect_pipeline.utils.test_set import make_test_set
from aspect_pipeline.utils.compare import (
    compare_exact,
    compare_format,
    print_exact_comparison,
    print_format_comparison,
)

def main() -> None:
    """
    Command line interface for ASPECT pipeline.
    Commands:
    - run: runs the pipeline according to the configurations
    - view: visualise a FITS file
    - pds4: generate a PDS4 product according to the configurations
    - make-test-set: generate a synthetic raw/calibration test set
    - compare-exact: byte-by-byte comparison of two json, bin or fits files
    - compare-format: format-aware (content) comparison of two json, bin or fits files
    """

    parser = argparse.ArgumentParser(prog="aspect")
    sub = parser.add_subparsers(dest="cdm", required=True)

    log_options = argparse.ArgumentParser(add_help=False)
    verbosity = log_options.add_mutually_exclusive_group()
    verbosity.add_argument("-v", "--verbose", action="store_true", help="Show debug messages")
    verbosity.add_argument("-q", "--quiet", action="store_true", help="Show only warnings and errors")

    run = sub.add_parser("run", help="Run the pipeline", parents=[log_options])
    run.add_argument(
        "--config",
        default=None,
        help="Path to YAML configurations. If omitted, searches for configs/example.yaml"
    )

    pds4 = sub.add_parser("pds4", help="Generate PDS4 products", parents=[log_options])
    pds4.add_argument(
        "--config",
        default=None,
        help="Path to YAML config. If omitted, searches default options"
    )


    test = sub.add_parser("test", help="Run a minimal pipeline test", parents=[log_options])
    test.add_argument(
        "--nn",
        action="store_true",
        help="Run the composition and taxonomy neural networks on a spectral data file"
    )
    test.add_argument(
        "--spectra",
        default=None,
        help="Path to the spectral data file. If omitted, uses the file in data/spectral"
    )
    test.add_argument(
        "--instrument",
        default="Vis-NIR1-NIR2",
        help="Instrument models to use: 'Vis-NIR1-NIR2' (default) or 'NIR1-NIR2'"
    )

    view = sub.add_parser("view", help="Visualise a fits or bin file", parents=[log_options])
    view_group = view.add_mutually_exclusive_group(required=True)
    view_group.add_argument(
        "--fits",
        default=None,
        help="Path to the FITS file to visualise"
    )
    view_group.add_argument(
        "--bin",
        default=None,
        help="Path to the .bin file to visualise"
    )

    make_test = sub.add_parser("make-test-set", help="Generate a synthetic raw/calibration test set", parents=[log_options])
    make_test.add_argument(
        "--input",
        required=True,
        help="Output directory for raw per-channel frames"
    )
    make_test.add_argument(
        "--calibration",
        required=True,
        help="Output directory for calibration files (TEST_DARK/, TEST_FLATS/)"
    )

    compare_commands = {
        "compare-exact": ("Byte-by-byte comparison of two files", "differing byte ranges"),
        "compare-format": ("Format-aware comparison of two files' content", "differences"),
    }
    for name, (help_text, diff_unit) in compare_commands.items():
        compare = sub.add_parser(name, help=help_text, parents=[log_options])
        compare_group = compare.add_mutually_exclusive_group(required=True)
        for ftype in ("json", "bin", "fits"):
            compare_group.add_argument(
                f"--{ftype}",
                dest="filetype",
                action="store_const",
                const=ftype,
                help=f"Compare two {ftype} files"
            )
        compare.add_argument("file_a", help="Path to the first file")
        compare.add_argument("file_b", help="Path to the second file")
        compare.add_argument(
            "--max-diffs",
            type=int,
            default=20,
            help=f"Maximum number of {diff_unit} to show (default: 20)"
        )

    args = parser.parse_args()

    setup_logging('DEBUG' if args.verbose else 'WARNING' if args.quiet else 'INFO')

    try: 
        if args.cdm == "run":
            config_path = Path(args.config).expanduser() if args.config else None
            run_pipeline(config_path=config_path)
        if args.cdm == "pds4":
            config_path = Path(args.config).expanduser() if args.config else None
            run_generate_pds4(config_path=config_path)
        if args.cdm == "test":
            if args.nn:
                from aspect_pipeline.levels.level_3.try_level_3 import try_nn, DEFAULT_SPECTRA
                spectra_path = Path(args.spectra).expanduser() if args.spectra else DEFAULT_SPECTRA
                try_nn(spectra_path=spectra_path, instrument=args.instrument)
            else:
                hello()
        if args.cdm == "view":
            if args.fits:
                visualise_fits_file(Path(args.fits).expanduser())
            elif args.bin:
                visualise_bin_file(Path(args.bin).expanduser())
        if args.cdm == "make-test-set":
            make_test_set(Path(args.input).expanduser(), Path(args.calibration).expanduser())
        if args.cdm == "compare-exact":
            result = compare_exact(
                Path(args.file_a).expanduser(),
                Path(args.file_b).expanduser(),
                args.filetype,
                max_ranges=args.max_diffs,
            )
            print_exact_comparison(result)
            if not result.identical:
                raise SystemExit(1)
        if args.cdm == "compare-format":
            result = compare_format(
                Path(args.file_a).expanduser(),
                Path(args.file_b).expanduser(),
                args.filetype,
                max_diffs=args.max_diffs,
            )
            print_format_comparison(result)
            if not result.identical:
                raise SystemExit(1)
    except PipelineError as e:
        raise SystemExit()

if __name__ == "__main__":
    main()
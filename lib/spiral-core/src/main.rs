use clap::{Parser, Subcommand};

mod check_done;
mod merge;
mod merge_workers;
mod partition;
mod prd;
mod synthesize;
mod validate;

#[derive(Parser)]
#[command(name = "spiral-core", about = "SPIRAL hot-path utilities (replaces Python scripts)")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Validate prd.json schema and dependency DAG (replaces prd_schema.py + check_dag.py)
    Validate {
        /// Path to prd.json
        prd: String,
        /// Suppress success message
        #[arg(long)]
        quiet: bool,
    },

    /// Merge story candidates into prd.json (replaces merge_stories.py)
    Merge {
        #[arg(long, default_value = "prd.json")]
        prd: String,
        #[arg(long, default_value = ".spiral/_research_output.json")]
        research: String,
        #[arg(long, default_value = ".spiral/_test_stories_output.json")]
        test_stories: String,
        #[arg(long, default_value = "")]
        overflow_in: String,
        #[arg(long, default_value = "")]
        overflow_out: String,
        #[arg(long, default_value_t = 50)]
        max_new: usize,
        #[arg(long, default_value_t = 0)]
        max_pending: usize,
        #[arg(long, default_value = "")]
        focus: String,
    },

    /// Synthesize test failure stories (replaces synthesize_tests.py)
    Synthesize {
        #[arg(long, default_value = "prd.json")]
        prd: String,
        #[arg(long, default_value = "test-reports")]
        reports_dir: String,
        #[arg(long, default_value = ".spiral/_test_stories_output.json")]
        output: String,
        #[arg(long, default_value_t = 3)]
        recent_reports: usize,
        #[arg(long, default_value = ".")]
        repo_root: String,
        #[arg(long, default_value = "")]
        focus: String,
    },

    /// Partition prd.json for parallel workers (replaces partition_prd.py)
    Partition {
        #[arg(long)]
        prd: String,
        #[arg(long, default_value_t = 0)]
        workers: usize,
        #[arg(long, default_value = "")]
        outdir: String,
        /// Print number of pending stories at topological level N, then exit
        #[arg(long)]
        wave_count: Option<usize>,
        /// Print total number of topological levels, then exit
        #[arg(long)]
        list_waves: bool,
        /// Only partition stories at topological level N
        #[arg(long)]
        wave_level: Option<usize>,
    },

    /// Check if SPIRAL is done (replaces check_done.py)
    CheckDone {
        #[arg(long, default_value = "prd.json")]
        prd: String,
        #[arg(long, default_value = "test-reports")]
        reports_dir: String,
    },

    /// Merge worker prd results into main prd (replaces merge_worker_results.py)
    MergeWorkers {
        #[arg(long)]
        main: String,
        #[arg(long, num_args = 1..)]
        workers: Vec<String>,
    },
}

fn main() {
    let cli = Cli::parse();
    let exit_code = match cli.command {
        Commands::Validate { prd, quiet } => validate::run(&prd, quiet),
        Commands::Merge {
            prd,
            research,
            test_stories,
            overflow_in,
            overflow_out,
            max_new,
            max_pending,
            focus,
        } => merge::run(
            &prd,
            &research,
            &test_stories,
            &overflow_in,
            &overflow_out,
            max_new,
            max_pending,
            &focus,
        ),
        Commands::Synthesize {
            prd,
            reports_dir,
            output,
            recent_reports,
            repo_root,
            focus,
        } => synthesize::run(&prd, &reports_dir, &output, recent_reports, &repo_root, &focus),
        Commands::Partition {
            prd,
            workers,
            outdir,
            wave_count,
            list_waves,
            wave_level,
        } => partition::run(&prd, workers, &outdir, wave_count, list_waves, wave_level),
        Commands::CheckDone { prd, reports_dir } => check_done::run(&prd, &reports_dir),
        Commands::MergeWorkers { main, workers } => merge_workers::run(&main, &workers),
    };
    std::process::exit(exit_code);
}

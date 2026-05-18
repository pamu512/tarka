//! Offline bulk ingest: CSV rows → ClickHouse ``fraud_features_offline`` with checkpointing.
//! **Never** publishes to ``fraud.decisions.>`` or calls decision-api (prevents analyst queue flood).

use anyhow::{Context, Result};
use clap::Parser;
use clickhouse::Row;
use serde::Serialize;
use serde_json::json;
use std::fs::OpenOptions;
use std::io::{BufReader, Write};
use std::path::PathBuf;
use tracing::{error, info, warn};

#[derive(Parser, Debug)]
#[command(name = "batch-ingest")]
struct Args {
    /// CSV path (header row required: tenant_id,entity_id,observed_at,feature_json optional columns).
    #[arg(long, env = "BATCH_CSV_PATH")]
    csv: PathBuf,
    #[arg(long, default_value = "http://localhost:8123")]
    clickhouse_url: String,
    #[arg(long, default_value = "fraud")]
    clickhouse_database: String,
    /// Checkpoint file: last successfully processed line number (1-based, after header).
    #[arg(long, default_value = "./data/batch-ingest-checkpoint.txt")]
    checkpoint_path: PathBuf,
    #[arg(long, default_value = "500")]
    batch_size: usize,
}

#[derive(Debug, Row, Serialize)]
struct FeatureOfflineRow {
    tenant_id: String,
    entity_id: String,
    observed_at: String,
    vector_json: String,
}

fn read_checkpoint(path: &PathBuf) -> u64 {
    std::fs::read_to_string(path)
        .ok()
        .and_then(|s| s.trim().parse().ok())
        .unwrap_or(0)
}

fn write_checkpoint(path: &PathBuf, line: u64) -> Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).ok();
    }
    let mut f = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(path)
        .with_context(|| format!("open checkpoint {:?}", path))?;
    writeln!(f, "{}", line)?;
    Ok(())
}

#[tokio::main]
async fn main() -> Result<()> {
    let _ = tarka_core::tracing_elk::try_install_elk_json_tracing();
    dotenvy::dotenv().ok();
    let args = Args::parse();
    let start_line = read_checkpoint(&args.checkpoint_path);
    info!(
        "batch-ingest starting csv={:?} checkpoint_line={} (no NATS / no decision-api)",
        args.csv, start_line
    );

    let ch = clickhouse::Client::default()
        .with_url(args.clickhouse_url.trim_end_matches('/'))
        .with_database(&args.clickhouse_database);

    let f = std::fs::File::open(&args.csv).with_context(|| format!("open csv {:?}", args.csv))?;
    let mut rdr = csv::Reader::from_reader(BufReader::new(f));
    let headers = rdr
        .headers()
        .context("csv headers")?
        .clone();
    let tenant_i = headers
        .iter()
        .position(|h| h.eq_ignore_ascii_case("tenant_id"))
        .context("csv must include tenant_id column")?;
    let entity_i = headers
        .iter()
        .position(|h| h.eq_ignore_ascii_case("entity_id"))
        .context("csv must include entity_id column")?;
    let time_i = headers
        .iter()
        .position(|h| {
            h.eq_ignore_ascii_case("observed_at")
                || h.eq_ignore_ascii_case("event_time")
                || h.eq_ignore_ascii_case("timestamp")
        })
        .context("csv must include observed_at (or event_time/timestamp) column")?;

    let mut batch: Vec<FeatureOfflineRow> = Vec::with_capacity(args.batch_size.max(1));
    let mut line_no: u64 = 0;
    for rec in rdr.records() {
        line_no += 1;
        if line_no <= start_line {
            continue;
        }
        let rec = rec.context("csv record")?;
        let tenant_id = rec.get(tenant_i).unwrap_or("").trim().to_string();
        let entity_id = rec.get(entity_i).unwrap_or("").trim().to_string();
        let observed_at = rec.get(time_i).unwrap_or("").trim().to_string();
        if tenant_id.is_empty() || entity_id.is_empty() {
            warn!("skip line {}: missing tenant_id/entity_id", line_no);
            continue;
        }
        let mut obj = json!({});
        for (i, h) in headers.iter().enumerate() {
            if let Some(v) = rec.get(i) {
                obj[h] = json!(v);
            }
        }
        let vector_json = serde_json::to_string(&obj).unwrap_or_else(|_| "{}".into());
        batch.push(FeatureOfflineRow {
            tenant_id,
            entity_id,
            observed_at,
            vector_json,
        });
        if batch.len() >= args.batch_size {
            flush_batch(&ch, &mut batch, line_no, &args.checkpoint_path).await?;
        }
    }
    flush_batch(&ch, &mut batch, line_no, &args.checkpoint_path).await?;
    info!("batch-ingest complete, last_line={}", line_no);
    Ok(())
}

async fn flush_batch(
    ch: &clickhouse::Client,
    batch: &mut Vec<FeatureOfflineRow>,
    line_no: u64,
    checkpoint: &PathBuf,
) -> Result<()> {
    if batch.is_empty() {
        return Ok(());
    }
    let res = async {
        let mut insert = ch
            .insert("fraud_features_offline")
            .context("clickhouse insert begin")?;
        for row in batch.iter() {
            insert.write(row).await.context("clickhouse write row")?;
        }
        insert.end().await.context("clickhouse end batch")?;
        Ok::<(), anyhow::Error>(())
    }
    .await;
    match res {
        Ok(()) => {
            write_checkpoint(checkpoint, line_no)?;
            batch.clear();
        }
        Err(e) => {
            error!("flush failed at line {}: {} — fix ClickHouse and rerun (checkpoint not advanced)", line_no, e);
            return Err(e);
        }
    }
    Ok(())
}

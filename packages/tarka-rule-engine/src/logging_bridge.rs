//! Minimal eval-span stubs for pack FFI.

pub struct EvalSpan;

impl EvalSpan {
    pub fn entered(self) -> EnteredEvalSpan {
        EnteredEvalSpan
    }
}

pub struct EnteredEvalSpan;

impl Drop for EnteredEvalSpan {
    fn drop(&mut self) {}
}

pub fn eval_context_span(_tenant: &str) -> EvalSpan {
    EvalSpan
}

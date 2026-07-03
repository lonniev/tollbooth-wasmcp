//! dpyc:crypto component — native secp256k1 + AES for the WASI CPython operator.
//!
//! `crypto_core` is pure and native-testable. The WIT binding layer is compiled
//! only for the wasm target, so `cargo test` validates the crypto natively
//! against wheel-generated vectors without needing the component machinery.

// Consumed by the WIT binding layer (wasm-only) and the tests; on a plain
// native lib build neither is active, so silence the unused-code lint.
#[allow(dead_code)]
mod crypto_core;

#[cfg(target_arch = "wasm32")]
#[allow(warnings)]
mod bindings;

#[cfg(target_arch = "wasm32")]
mod component {
    use crate::bindings::exports::dpyc::crypto::ops::Guest;
    use crate::crypto_core as cc;

    struct Component;

    impl Guest for Component {
        fn ecdh_nip04(privkey: Vec<u8>, pubkey_xonly: Vec<u8>) -> Result<Vec<u8>, String> {
            cc::ecdh_nip04(&privkey, &pubkey_xonly)
        }
        fn xonly_pubkey(privkey: Vec<u8>) -> Result<Vec<u8>, String> {
            cc::xonly_pubkey(&privkey)
        }
        fn schnorr_verify(msg: Vec<u8>, sig: Vec<u8>, pubkey_xonly: Vec<u8>) -> bool {
            cc::schnorr_verify(&msg, &sig, &pubkey_xonly)
        }
        fn aes256_cbc_decrypt(
            key: Vec<u8>,
            iv: Vec<u8>,
            ciphertext: Vec<u8>,
        ) -> Result<Vec<u8>, String> {
            cc::aes256_cbc_decrypt(&key, &iv, &ciphertext)
        }
        fn aes256_cbc_encrypt(
            key: Vec<u8>,
            iv: Vec<u8>,
            plaintext: Vec<u8>,
        ) -> Result<Vec<u8>, String> {
            cc::aes256_cbc_encrypt(&key, &iv, &plaintext)
        }
        fn aes256_gcm_decrypt(
            key: Vec<u8>,
            nonce: Vec<u8>,
            aad: Vec<u8>,
            ciphertext: Vec<u8>,
        ) -> Result<Vec<u8>, String> {
            cc::aes256_gcm_decrypt(&key, &nonce, &aad, &ciphertext)
        }
        fn aes256_gcm_encrypt(
            key: Vec<u8>,
            nonce: Vec<u8>,
            aad: Vec<u8>,
            plaintext: Vec<u8>,
        ) -> Result<Vec<u8>, String> {
            cc::aes256_gcm_encrypt(&key, &nonce, &aad, &plaintext)
        }
    }

    crate::bindings::export!(Component with_types_in crate::bindings);
}

#[cfg(test)]
mod tests {
    use super::crypto_core as cc;
    use base64::{engine::general_purpose::STANDARD, Engine};
    use serde_json::Value;

    fn vectors() -> Value {
        let raw = include_str!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/testdata/vectors.json"
        ));
        serde_json::from_str(raw).unwrap()
    }
    fn hx(v: &Value, k: &str) -> Vec<u8> {
        hex::decode(v[k].as_str().unwrap()).unwrap()
    }

    #[test]
    fn ecdh_matches_wheel_and_is_symmetric() {
        let v = vectors();
        let n = &v["nip04"];
        let priv_a = hex::decode(n["priv_a"].as_str().unwrap()).unwrap();
        let pub_b = hex::decode(n["pub_b_xonly"].as_str().unwrap()).unwrap();
        let priv_b = hex::decode(n["priv_b"].as_str().unwrap()).unwrap();
        let pub_a = hex::decode(n["pub_a_xonly"].as_str().unwrap()).unwrap();
        let expected = hex::decode(n["shared_x"].as_str().unwrap()).unwrap();

        let ab = cc::ecdh_nip04(&priv_a, &pub_b).unwrap();
        let ba = cc::ecdh_nip04(&priv_b, &pub_a).unwrap();
        assert_eq!(ab, expected, "ECDH X must match the wheel");
        assert_eq!(ab, ba, "ECDH must be symmetric");
    }

    #[test]
    fn xonly_pubkey_matches_wheel() {
        let v = vectors();
        let n = &v["nip04"];
        let priv_a = hex::decode(n["priv_a"].as_str().unwrap()).unwrap();
        let pub_a = hex::decode(n["pub_a_xonly"].as_str().unwrap()).unwrap();
        assert_eq!(cc::xonly_pubkey(&priv_a).unwrap(), pub_a);
    }

    #[test]
    fn nip04_decrypt_wheel_ciphertext() {
        // Recipient b decrypts a's NIP-04 message: ECDH(priv_b, pub_a) -> key,
        // then AES-256-CBC decrypt with the parsed iv.
        let v = vectors();
        let n = &v["nip04"];
        let priv_b = hex::decode(n["priv_b"].as_str().unwrap()).unwrap();
        let pub_a = hex::decode(n["pub_a_xonly"].as_str().unwrap()).unwrap();
        let ct_field = n["ciphertext_nip04"].as_str().unwrap();
        let (ct_b64, iv_b64) = ct_field.split_once("?iv=").unwrap();
        let ct = STANDARD.decode(ct_b64).unwrap();
        let iv = STANDARD.decode(iv_b64).unwrap();

        let key = cc::ecdh_nip04(&priv_b, &pub_a).unwrap();
        let pt = cc::aes256_cbc_decrypt(&key, &iv, &ct).unwrap();
        assert_eq!(
            String::from_utf8(pt).unwrap(),
            n["plaintext"].as_str().unwrap()
        );
    }

    #[test]
    fn cbc_roundtrip() {
        let key = [7u8; 32];
        let iv = [3u8; 16];
        let msg = b"the quick brown fox jumps over 13 lazy dogs!!";
        let ct = cc::aes256_cbc_encrypt(&key, &iv, msg).unwrap();
        let pt = cc::aes256_cbc_decrypt(&key, &iv, &ct).unwrap();
        assert_eq!(pt, msg);
    }

    #[test]
    fn aesgcm_decrypts_wheel_vault_rows() {
        let v = vectors();
        let g = &v["aesgcm_vault"];
        let key = hx(g, "derived_key");
        let expected = g["plaintext"].as_str().unwrap();

        // no-AAD row
        let raw = STANDARD
            .decode(g["ciphertext_b64"].as_str().unwrap())
            .unwrap();
        let (nonce, ct) = raw.split_at(12);
        let pt = cc::aes256_gcm_decrypt(&key, nonce, b"", ct).unwrap();
        assert_eq!(String::from_utf8(pt).unwrap(), expected);

        // AAD-bound row
        let raw2 = STANDARD
            .decode(g["ciphertext_b64_aad"].as_str().unwrap())
            .unwrap();
        let (nonce2, ct2) = raw2.split_at(12);
        let aad = g["aad"].as_str().unwrap().as_bytes();
        let pt2 = cc::aes256_gcm_decrypt(&key, nonce2, aad, ct2).unwrap();
        assert_eq!(String::from_utf8(pt2).unwrap(), expected);

        // wrong AAD must fail (tag mismatch)
        assert!(cc::aes256_gcm_decrypt(&key, nonce2, b"vault/wrong", ct2).is_err());
    }

    #[test]
    fn aesgcm_roundtrip() {
        let key = [9u8; 32];
        let nonce = [1u8; 12];
        let msg = br#"{"balance":123}"#;
        let ct = cc::aes256_gcm_encrypt(&key, &nonce, b"aad-ctx", msg).unwrap();
        let pt = cc::aes256_gcm_decrypt(&key, &nonce, b"aad-ctx", &ct).unwrap();
        assert_eq!(pt, msg);
    }

    #[test]
    fn schnorr_verifies_real_bootstrap_event() {
        // The real Tollbooth Sample bootstrap event, signed by its Authority.
        let v = vectors();
        let s = &v["schnorr_real_event"];
        let id = hex::decode(s["id"].as_str().unwrap()).unwrap();
        let sig = hex::decode(s["sig"].as_str().unwrap()).unwrap();
        let pubkey = hex::decode(s["pubkey"].as_str().unwrap()).unwrap();
        assert!(
            cc::schnorr_verify(&id, &sig, &pubkey),
            "real Authority sig must verify"
        );

        // Tampered id must NOT verify.
        let mut bad = id.clone();
        bad[0] ^= 0x01;
        assert!(!cc::schnorr_verify(&bad, &sig, &pubkey));
    }

    // Proves the crypto core decrypts a REAL Authority-published bootstrap event
    // (ECDH + AES-256-CBC) to the operator's Neon DSN. Reads a gitignored local
    // vector containing the test operator's private key; skips if absent.
    #[test]
    fn decrypts_real_bootstrap_event_if_local_vector_present() {
        let path = concat!(env!("CARGO_MANIFEST_DIR"), "/testdata/vectors.local.json");
        let raw = match std::fs::read_to_string(path) {
            Ok(r) => r,
            Err(_) => {
                eprintln!("skip: no gitignored local vector present");
                return;
            }
        };
        let v: Value = serde_json::from_str(&raw).unwrap();
        let op_priv = hex::decode(v["op_priv_hex"].as_str().unwrap()).unwrap();
        let auth = hex::decode(v["auth_hex"].as_str().unwrap()).unwrap();
        let ct = STANDARD.decode(v["ct_b64"].as_str().unwrap()).unwrap();
        let iv = STANDARD.decode(v["iv_b64"].as_str().unwrap()).unwrap();

        let key = cc::ecdh_nip04(&op_priv, &auth).unwrap();
        let pt = cc::aes256_cbc_decrypt(&key, &iv, &ct).unwrap();
        let cfg: Value = serde_json::from_slice(&pt).unwrap();
        let neon = cfg["config"]["neon_database_url"]
            .as_str()
            .or_else(|| cfg["neon_database_url"].as_str())
            .unwrap();
        assert_eq!(neon, v["expected_neon_url"].as_str().unwrap());
    }
}

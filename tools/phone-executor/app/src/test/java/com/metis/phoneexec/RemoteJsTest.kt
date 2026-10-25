package com.metis.phoneexec

import net.i2p.crypto.eddsa.EdDSAEngine
import net.i2p.crypto.eddsa.EdDSAPrivateKey
import net.i2p.crypto.eddsa.EdDSAPublicKey
import net.i2p.crypto.eddsa.KeyPairGenerator
import net.i2p.crypto.eddsa.spec.EdDSANamedCurveTable
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.security.MessageDigest
import java.util.Base64

/** The signed remote-script contract (PHONE-EXEC-OBSERVABLE-1018, piece 4): version pin, message, verify. */
class RemoteJsTest {
    private val spec = EdDSANamedCurveTable.getByName(EdDSANamedCurveTable.ED_25519)
    private val kp = KeyPairGenerator().generateKeyPair()
    private val pubB64 = Base64.getEncoder().encodeToString((kp.public as EdDSAPublicKey).abyte)

    private fun sign(msg: String): String {
        val eng = EdDSAEngine(MessageDigest.getInstance(spec.hashAlgorithm))
        eng.initSign(kp.private as EdDSAPrivateKey); eng.update(msg.toByteArray())
        return Base64.getEncoder().encodeToString(eng.sign())
    }

    private val js = "(function () {\n  var EXEC_VERSION = \"2026-10-18.1\";\n  window.__ex = {version: EXEC_VERSION};\n})();\n"

    @Test fun versionIsReadFromTheScriptItself() {
        assertEquals("2026-10-18.1", RemoteJs.versionOf(js))
        assertEquals("", RemoteJs.versionOf("var x = 1;"))
        assertEquals("", RemoteJs.versionOf("var EXEC_VERSION = \"latest\";"))
    }

    @Test fun newerComparesDateThenCounter() {
        assertTrue(RemoteJs.newer("2026-10-18.2", "2026-10-18.1"))
        assertTrue(RemoteJs.newer("2026-10-19.1", "2026-10-18.9"))
        assertTrue(RemoteJs.newer("2026-10-18.10", "2026-10-18.9"))
        assertFalse(RemoteJs.newer("2026-10-18.1", "2026-10-18.1"))
        assertFalse(RemoteJs.newer("2026-10-17.5", "2026-10-18.1"))
        assertFalse(RemoteJs.newer("garbage", "2026-10-18.1"))
        assertTrue(RemoteJs.newer("2026-10-18.1", ""))
    }

    @Test fun messageIsTheDeclaredShape() {
        assertEquals("metis-exec-js\n2026-10-18.1\nabc", RemoteJs.message("2026-10-18.1", "abc"))
        assertEquals(64, RemoteJs.sha256Hex(js).length)
    }

    @Test fun acceptsOnlyAValidSignatureOverTheVersionAndTheExactBytes() {
        val v = "2026-10-18.1"
        val sig = sign(RemoteJs.message(v, RemoteJs.sha256Hex(js)))
        assertTrue(RemoteJs.accept(pubB64, js, v, sig))
        assertFalse("one byte changed", RemoteJs.accept(pubB64, js + " ", v, sig))
        assertFalse("version claimed differs from the pin inside", RemoteJs.accept(pubB64, js, "2026-10-18.2", sig))
        assertFalse("signature from another key", RemoteJs.accept(Base64.getEncoder().encodeToString((KeyPairGenerator().generateKeyPair().public as EdDSAPublicKey).abyte), js, v, sig))
        assertFalse("no key = disabled", RemoteJs.accept("", js, v, sig))
        assertFalse("malformed signature", RemoteJs.accept(pubB64, js, v, "not base64 at all"))
        assertFalse("wrong-length signature", RemoteJs.accept(pubB64, js, v, Base64.getEncoder().encodeToString(ByteArray(10))))
    }

    /** INTEROP with the CI signer: a fixed vector produced by `openssl genpkey -algorithm ed25519` +
     *  `openssl pkeyutl -sign -rawin` (the phone-exec-js-sign workflow's exact commands), the raw 32-byte public key
     *  from `openssl pkey -pubout -outform DER | tail -c 32`. If this fails, the app and CI disagree on Ed25519. */
    @Test fun verifiesAnOpensslProducedSignature() {
        val pub = "3QX06sUHYA6E2+TMb7zX7wXvLYZm7jWhLjSH6fm6KcY="
        val msg = RemoteJs.message("2026-10-18.1", "abc")
        val sig = "NOTh1Vyjs6cOCqOLqrjyDZdxX+568VBQs7IXCm6ePiIG8SLuXZXVZM+LZpID7MHxzwJ4e7SK0ToH6rqhLvkTDg=="
        assertTrue(RemoteJs.verify(pub, msg, sig))
        assertFalse(RemoteJs.verify(pub, msg + "x", sig))
    }

    @Test fun theBundledScriptCarriesAVersionPin() {
        val src = java.io.File("src/main/assets/exec.js").readText()
        val v = RemoteJs.versionOf(src)
        assertTrue("exec.js must declare var EXEC_VERSION = \"YYYY-MM-DD.N\"; (got '$v')", Regex("""\d{4}-\d{2}-\d{2}\.\d+""").matches(v))
        assertTrue("exec.js re-injection guard must compare the version", src.contains("window.__ex.version === EXEC_VERSION"))
    }
}

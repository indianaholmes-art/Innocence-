package dev.subg.app

/** Byte-line transport to the RF Bridge (real USB CDC or the built-in simulator). */
interface Transport {
    val name: String
    val isOpen: Boolean
    /** Starts I/O. [onLine] gets each received text line, [onClosed] fires once on disconnect. */
    fun open(onLine: (String) -> Unit, onClosed: (String) -> Unit)
    fun writeLine(line: String)
    fun close()
}

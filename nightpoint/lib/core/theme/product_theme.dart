import 'package:flutter/material.dart';

/// Design System v2 tokens. Platform typography keeps its bundled attribution.
class ProductTheme {
  static ThemeData forBrightness(Brightness brightness) {
    final dark = brightness == Brightness.dark;
    final scheme = ColorScheme.fromSeed(
      seedColor: const Color(0xFF8350F2),
      brightness: brightness,
      surface: Color(dark ? 0xFF171722 : 0xFFFFFFFF),
    );
    return ThemeData(
      useMaterial3: true,
      brightness: brightness,
      colorScheme: scheme,
      scaffoldBackgroundColor: Color(dark ? 0xFF0D0D14 : 0xFFF3F3F8),
      cardTheme: CardThemeData(
        color: Color(dark ? 0xFF242433 : 0xFFFFFFFF),
        margin: const EdgeInsets.symmetric(vertical: 6),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: Color(dark ? 0xFF242433 : 0xFFE7E7EF),
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
      ),
      appBarTheme: const AppBarTheme(centerTitle: false),
    );
  }
}

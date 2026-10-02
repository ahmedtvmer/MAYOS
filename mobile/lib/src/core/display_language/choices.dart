import 'package:flutter/material.dart';

import 'catalog.dart';

/// The shared language choices used by both logged-out and account Settings selectors.
List<DropdownMenuItem<String>> displayLanguageMenuItems(MayosCopy copy) =>
    <DropdownMenuItem<String>>[
      DropdownMenuItem(value: 'en', child: Text(copy.english)),
      DropdownMenuItem(value: 'ar', child: Text(copy.arabic)),
    ];
